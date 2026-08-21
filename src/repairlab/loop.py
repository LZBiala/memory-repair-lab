"""The repair loop - an agentic control graph over the memory substrate.

The graph, drawn in prose (each node is a role, each edge an artifact):

  MEMORY (wiki notes) --index--> EVALUATOR --misses--> FAILURE RECORDS
  FAILURE RECORDS --citations--> REPAIRER --candidate edits--> GATES
  GATES (regression replay, citation check) --accepted diffs--> MEMORY

Roles are structurally separated, family-style: the evaluator only scores,
the repairer only proposes (and may read ONLY failure records and target
note bodies - a test asserts held-out task text never enters its input),
and the gates alone decide what lands. Every accepted edit carries a written
reason plus the id of the failure record that motivated it; the ledger
refuses anything less. The placebo arm receives the same edit budget with
the failure-record edge CUT - separating "the failure signal helps" from
"any editing helps".

The model never learns; the notes do.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from repairlab.corpus import Note, index_text, proxy_tokens, recall_names


class LoopError(ValueError):
    """Raised when the loop's structural rules are violated."""


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    target: str
    recalled: tuple[str, ...]
    hit: bool


@dataclass(frozen=True)
class ArmEval:
    arm: str
    split: str  # repair_visible | held_out
    hits: int
    total: int
    precision: str  # correct recalls / total recalls, pin-formatted
    index_tokens: int
    results: tuple[TaskResult, ...]


@dataclass(frozen=True)
class FailureRecord:
    failure_id: str
    task_id: str
    target: str
    question: str  # repair-visible phrasing only, by construction
    observed: str


@dataclass(frozen=True)
class RepairEdit:
    note: str
    old_hook: str
    new_hook: str
    reason: str
    citation: str  # failure_id - mandatory


def evaluate(notes: dict[str, Note], tasks: list[dict[str, str]], split: str, arm: str) -> ArmEval:
    results = []
    for t in tasks:
        recalled = tuple(recall_names(t[split], notes))
        results.append(
            TaskResult(
                task_id=t["id"], target=t["relevant"], recalled=recalled,
                hit=t["relevant"] in recalled,
            )
        )
    n_recalled = sum(len(r.recalled) for r in results)
    n_correct = sum(1 for r in results if r.hit)
    precision = f"{n_correct / n_recalled:.2f}" if n_recalled else "n/a"
    return ArmEval(
        arm=arm, split=split,
        hits=n_correct, total=len(results), precision=precision,
        index_tokens=proxy_tokens(index_text(notes)), results=tuple(results),
    )


def file_failures(gen0: ArmEval) -> list[FailureRecord]:
    """Misses on the REPAIR-VISIBLE split become typed failure records."""
    if gen0.split != "repair_visible":
        raise LoopError("failures are filed from the repair-visible split only")
    records = []
    for r in gen0.results:
        if not r.hit:
            records.append(
                FailureRecord(
                    failure_id=f"fail-{r.task_id}",
                    task_id=r.task_id,
                    target=r.target,
                    question="",  # filled by caller from the repair-visible phrasing
                    observed=f"recalled {list(r.recalled)!r}, needed {r.target!r}",
                )
            )
    return records


def failure_note(record: FailureRecord) -> Note:
    body = "\n".join(
        [
            f"task: {record.task_id}",
            f"target: {record.target}",
            "generation: 0",
            f"question: {record.question}",
            f"observed: {record.observed}",
        ]
    )
    return Note(
        name=record.failure_id,
        hook=f"retrieval miss on {record.target} (task {record.task_id})",
        kind="failure",
        body=body,
    )


def repair(
    notes: dict[str, Note], failures: list[FailureRecord]
) -> list[RepairEdit]:
    """The scripted repairer: for each failure, rewrite the target note's hook
    FROM THE NOTE'S OWN BODY (content-derived, not task-derived - so held-out
    phrasings can only be won by genuinely better metadata, not by echoing
    the visible question). Deterministic; one edit per failure."""
    edits = []
    for record in sorted(failures, key=lambda f: f.failure_id):
        if record.target not in notes:
            raise LoopError(
                f"failure {record.failure_id!r} cites missing note {record.target!r}"
            )
        target = notes[record.target]
        first_line = target.body.split("\n")[0].strip().rstrip(".")
        edits.append(
            RepairEdit(
                note=record.target,
                old_hook=target.hook,
                new_hook=first_line,
                reason=(
                    f"hook {target.hook!r} carried no retrievable signal; "
                    "rewritten from the note's own first line"
                ),
                citation=record.failure_id,
            )
        )
    return edits


def placebo_edits(notes: dict[str, Note], budget: int) -> list[RepairEdit]:
    """The churn arm: SAME edit budget, computed blind - no failure records in
    sight. Deterministic rule: rewrite the hooks of the alphabetically first
    `budget` memory notes to a generic template."""
    # Same EDIT RULE as the repair arm (first-line rewrite) so the only
    # difference between arms is the failure signal choosing the targets -
    # not a weak rule losing to a strong one.
    targets = sorted(n for n, note in notes.items() if note.kind == "memory")[:budget]
    return [
        RepairEdit(
            note=name,
            old_hook=notes[name].hook,
            new_hook=notes[name].body.split("\n")[0].strip().rstrip("."),
            reason="placebo churn: budget-matched first-line rewrite, blind to failure records",
            citation="placebo-arm",
        )
        for name in targets
    ]


def bloat_edits(notes: dict[str, Note]) -> list[RepairEdit]:
    """The Goodhart strategy, shipped on purpose: maximize recall by stuffing
    every hook with the whole note body. Recall rises; the index balloons.
    An authored demonstration of a failure mode, not a recommendation."""
    return [
        RepairEdit(
            note=name,
            old_hook=note.hook,
            new_hook=" ".join(note.body.split("\n")).strip(),
            reason="goodhart demo: hook bloated to full body to game recall",
            citation="goodhart-demo",
        )
        for name, note in sorted(notes.items())
        if note.kind == "memory"
    ]


def apply_edits(notes: dict[str, Note], edits: list[RepairEdit]) -> dict[str, Note]:
    out = dict(notes)
    for e in edits:
        if not e.reason.strip() or not e.citation.strip():
            raise LoopError(f"uncited or unexplained edit on {e.note!r} refused")
        if "\n" in e.new_hook or "\r" in e.new_hook or e.new_hook.startswith("---"):
            raise LoopError(f"hook for {e.note!r} must be a single plain line")
        old = out[e.note]
        out[e.note] = Note(name=old.name, hook=e.new_hook, kind=old.kind, body=old.body)
    return out


def regression_gate(
    before: dict[str, Note],
    edits: list[RepairEdit],
    tasks: list[dict[str, str]],
) -> tuple[dict[str, Note], list[RepairEdit], list[tuple[RepairEdit, str]]]:
    """Accept edits one at a time; replay the FULL repair-visible suite after
    each. An edit that breaks a previously-passing task is reverted with a
    ledgered reason. Returns (final notes, accepted, reverted+reasons)."""
    # The baseline is RECOMPUTED after every acceptance: an edit must protect
    # everything passing AT THAT MOMENT, including tasks an earlier edit in
    # this same batch just fixed. (A batch-start-only baseline let later
    # collateral edits re-break interim fixes - caught by independent review.)
    current = dict(before)
    baseline = {
        r.task_id: r.hit
        for r in evaluate(current, tasks, "repair_visible", "gate-baseline").results
    }
    accepted: list[RepairEdit] = []
    reverted: list[tuple[RepairEdit, str]] = []
    for edit in edits:
        candidate = apply_edits(current, [edit])
        replay = evaluate(candidate, tasks, "repair_visible", "gate-replay")
        broken = [
            r.task_id for r in replay.results if baseline[r.task_id] and not r.hit
        ]
        if broken:
            reverted.append(
                (edit, f"reverted: repair on {edit.note!r} broke {broken!r}")
            )
        else:
            current = candidate
            accepted.append(edit)
            baseline = {r.task_id: r.hit for r in replay.results}
    return current, accepted, reverted


_AUDIT_WORD_RE = re.compile(r"[a-z0-9']+")


def _normalize(text: str) -> str:
    return " ".join(_AUDIT_WORD_RE.findall(text.lower()))


def holdout_isolation_audit(
    repairer_inputs: list[str], tasks: list[dict[str, str]]
) -> None:
    """The held-out wall, enforced: no held-out phrasing may appear in any
    string the repairer consumed. Both sides are punctuation-normalized so a
    dropped question mark cannot smuggle a phrasing past the audit (a probe
    proved the naive substring check evadable). Raises on breach."""
    normalized_inputs = [_normalize(text) for text in repairer_inputs]
    for t in tasks:
        held = _normalize(t["held_out"])
        for text in normalized_inputs:
            if held and held in text:
                raise LoopError(f"held-out phrasing for {t['id']} leaked into repairer input")


def write_ledger(
    path: Path,
    accepted: list[RepairEdit],
    reverted: list[tuple[RepairEdit, str]],
    stop_reason: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for e in accepted:
            fh.write(json.dumps({
                "action": "ACCEPT", "note": e.note, "old_hook": e.old_hook,
                "new_hook": e.new_hook, "reason": e.reason, "citation": e.citation,
            }, sort_keys=True) + "\n")
        for e, why in reverted:
            fh.write(json.dumps({
                "action": "REVERT", "note": e.note, "reason": why,
                "citation": e.citation,
            }, sort_keys=True) + "\n")
        fh.write(json.dumps({"action": "STOP", "reason": stop_reason}, sort_keys=True) + "\n")
