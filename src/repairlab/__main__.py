"""CLI: `python -m repairlab demo` - the whole loop, from clean state, no keys.

Streams the story: generation-0 evaluation → misses filed as failure notes →
cited repairs through the regression gate (plus the blind placebo arm and the
Goodhart bloat arm) → held-out re-measurement → the stop rule. Regenerates
wiki/, runs/, report/, metrics.jsonl, and the README AUTOGEN block; CI runs
exactly this then `git diff --exit-code`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from repairlab.corpus import Note, index_text
from repairlab.loop import (
    apply_edits,
    bloat_edits,
    evaluate,
    failure_note,
    file_failures,
    holdout_isolation_audit,
    placebo_edits,
    regression_gate,
    repair,
    write_ledger,
)
from repairlab.report import (
    inject_readme,
    load_metrics,
    render_claims,
    render_generations_svg,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "corpus.json"
WIKI_DIR = REPO_ROOT / "wiki"
RUNS_DIR = REPO_ROOT / "runs"
REPORT_DIR = REPO_ROOT / "report"
METRICS = REPO_ROOT / "metrics.jsonl"
README = REPO_ROOT / "README.md"

BANNER = (
    "LOOP: scripted evaluator/repairer - deterministic, zero API keys; "
    "the model never learns, the notes do"
)


def _clean_tree(path: Path) -> None:
    if not path.exists():
        return
    for p in sorted(path.rglob("*"), reverse=True):
        if p.is_file():
            p.unlink()
        else:
            try:
                p.rmdir()
            except OSError:
                pass  # held directory handles are harmless; files are gone
    try:
        path.rmdir()
    except OSError:
        pass


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def demo(quiet: bool) -> int:
    if not FIXTURE.exists():
        print(f"repairlab demo needs a source checkout - missing {FIXTURE}", file=sys.stderr)
        return 1
    emit = (lambda _line: None) if quiet else print
    emit(BANNER)
    emit("")

    for path in (WIKI_DIR, RUNS_DIR, REPORT_DIR):
        _clean_tree(path)
    if METRICS.exists():
        METRICS.unlink()

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    notes = {
        n["name"]: Note(name=n["name"], hook=n["hook"], kind="memory", body=n["body"])
        for n in data["notes"]
    }
    tasks = data["tasks"]

    gen0_visible = evaluate(notes, tasks, "repair_visible", "gen0")
    gen0_held = evaluate(notes, tasks, "held_out", "gen0-frozen")
    emit(f"GEN 0: repair-visible {gen0_visible.hits}/{gen0_visible.total}; "
         f"held-out {gen0_held.hits}/{gen0_held.total}")

    failures = []
    visible_by_id = {t["id"]: t["repair_visible"] for t in tasks}
    for record in file_failures(gen0_visible):
        completed = type(record)(
            failure_id=record.failure_id, task_id=record.task_id,
            target=record.target, question=visible_by_id[record.task_id],
            observed=record.observed,
        )
        failures.append(completed)
        note = failure_note(completed)
        _write(RUNS_DIR / "failures" / f"{note.name}.md", note.render())
        emit(f"FAILURE FILED: {note.name} - {note.hook}")

    edits = repair(notes, failures)
    repairer_inputs = [f.question + " " + f.observed for f in failures] + [
        notes[f.target].body for f in failures
    ]
    holdout_isolation_audit(repairer_inputs, tasks)
    emit("HELD-OUT WALL: audited - no held-out phrasing in repairer input")

    repaired, accepted, reverted = regression_gate(notes, edits, tasks)
    for e in accepted:
        emit(f"REPAIR ACCEPTED: {e.note} - {e.reason} [cites {e.citation}]")
    for e, why in reverted:
        emit(f"REPAIR REVERTED: {e.note} - {why}")

    mend_held = evaluate(repaired, tasks, "held_out", "repair")
    mend_visible = evaluate(repaired, tasks, "repair_visible", "repair")
    emit(f"GEN 1 (repair): repair-visible {mend_visible.hits}/{mend_visible.total}; "
         f"held-out {mend_held.hits}/{mend_held.total}")

    # The placebo arm goes through the SAME regression gate as the repair arm:
    # the only remaining difference between arms is who chose the targets.
    placebo, _pl_acc, _pl_rev = regression_gate(
        notes, placebo_edits(notes, budget=len(accepted)), tasks
    )
    pla_held = evaluate(placebo, tasks, "held_out", "placebo")
    emit(f"GEN 1 (placebo, blind, same budget): held-out {pla_held.hits}/{pla_held.total}")

    bloated = apply_edits(notes, bloat_edits(notes))
    blo_held = evaluate(bloated, tasks, "held_out", "goodhart-bloat")
    emit(f"GEN 1 (goodhart bloat): held-out {blo_held.hits}/{blo_held.total} "
         f"at index {blo_held.index_tokens} tok (repair arm: {mend_held.index_tokens} tok)")

    remaining = [r for r in mend_visible.results if not r.hit]
    stop_reason = (
        "no remaining repair-visible failures after generation 1"
        if not remaining
        else f"{len(remaining)} failures remain but the edit budget is exhausted"
    )
    emit(f"STOP: {stop_reason}")
    write_ledger(RUNS_DIR / "repair-ledger.jsonl", accepted, reverted, stop_reason)

    for name, note in sorted(repaired.items()):
        _write(WIKI_DIR / f"{name}.md", note.render())
    _write(WIKI_DIR / "index.md", index_text(repaired))

    rows = []
    for ev in (gen0_visible, gen0_held, mend_visible, mend_held, pla_held, blo_held):
        rows.append({
            "kind": "arm", "arm": ev.arm, "split": ev.split, "hits": ev.hits,
            "total": ev.total, "precision": ev.precision,
            "index_tokens": ev.index_tokens,
        })
    cited = sum(1 for e in accepted if e.citation.strip())
    rows.append({
        "kind": "summary", "accepted": len(accepted), "reverted": len(reverted),
        "citation_coverage": f"{cited}/{len(accepted)}", "stop_reason": stop_reason,
    })
    with METRICS.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    metrics = load_metrics(METRICS)
    _write(REPORT_DIR / "generations.svg", render_generations_svg(metrics))
    inject_readme(README, render_claims(metrics))

    emit("")
    emit("Look around:")
    emit("  wiki/                 the repaired memory (gen 1) - diff it against fixtures/corpus.json")
    emit("  runs/failures/        every miss, filed as a typed note")
    emit("  runs/repair-ledger.jsonl  ACCEPT/REVERT/STOP, each with reason + citation")
    emit("  report/generations.svg    the four arms, gains and prices together")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repairlab")
    sub = parser.add_subparsers(dest="command", required=True)
    p_demo = sub.add_parser("demo", help="run the full loop from clean state (no keys)")
    p_demo.add_argument("--quiet", action="store_true", help="print nothing (CI mode)")
    args = parser.parse_args(argv)
    return demo(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
