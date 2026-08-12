"""The repair loop — an agentic control graph over the memory substrate.

The graph, drawn in prose (each node is a role, each edge an artifact):

  MEMORY (wiki notes) --index--> EVALUATOR --misses--> FAILURE RECORDS
  FAILURE RECORDS --citations--> REPAIRER --candidate edits--> GATES
  GATES (regression replay, citation check) --accepted diffs--> MEMORY

Roles are structurally separated, family-style: the evaluator only scores,
the repairer only proposes (and may read ONLY failure records and target
note bodies — a test asserts held-out task text never enters its input),
and the gates alone decide what lands. Every accepted edit carries a written
reason plus the id of the failure record that motivated it; the ledger
refuses anything less. The placebo arm receives the same edit budget with
the failure-record edge CUT — separating "the failure signal helps" from
"any editing helps".

The model never learns; the notes do.
"""
from __future__ import annotations

import json
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
    citation: str  # failure_id — mandatory


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
    return ArmEval(
        arm=arm, split=split,
        hits=sum(1 for r in results if r.hit), total=len(results),
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
    FROM THE NOTE'S OWN BODY (content-derived, not task-derived — so held-out
    phrasings can only be won by genuinely better metadata, not by echoing
    the visible question). Deterministic; one edit per failure."""
    edits = []
    for record in sorted(failures, key=lambda f: f.failure_id):
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
    """The churn arm: SAME edit budget, computed blind — no failure records in
    sight. Deterministic rule: rewrite the hooks of the alphabetically first
    `budget` memory notes to a generic template."""
    targets = sorted(n for n, note in notes.items() if note.kind == "memory")[:budget]
    return [
        RepairEdit(
            note=name,
            old_hook=notes[name].hook,
            new_hook=f"notes filed under {name.replace('-', ' ')}",
            reason="placebo churn: budget-matched edit, blind to failure records",
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
    baseline = {
        r.task_id: r.hit
        for r in evaluate(before, tasks, "repair_visible", "gate-baseline").results
    }
    current = dict(before)
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
    return current, accepted, reverted


def holdout_isolation_audit(
    repairer_inputs: list[str], tasks: list[dict[str, str]]
) -> None:
    """The held-out wall, enforced: no held-out phrasing may appear in any
    string the repairer consumed. Raises on breach; a test drives this."""
    for t in tasks:
        held = t["held_out"].lower()
        for text in repairer_inputs:
            if held in text.lower():
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
