"""Contract + pipeline suites: the citation law, the held-out wall, placebo
blindness, the regression gate (probed), determinism, keyless AST,
no-wallclock, hygiene gate, and README pins.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from repairlab.corpus import Note, parse_note, recall_names
from repairlab.loop import (
    LoopError,
    RepairEdit,
    apply_edits,
    evaluate,
    file_failures,
    holdout_isolation_audit,
    placebo_edits,
    regression_gate,
    repair,
)

REPO = Path(__file__).resolve().parents[1]
DATA = json.loads((REPO / "fixtures" / "corpus.json").read_text("utf-8"))
NOTES = {
    n["name"]: Note(name=n["name"], hook=n["hook"], kind="memory", body=n["body"])
    for n in DATA["notes"]
}
TASKS = DATA["tasks"]
WALLCLOCK_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}:\d{2}")


class TestCitationLaw:
    def test_uncited_edit_refused(self) -> None:
        bad = RepairEdit(note="bakery-hours", old_hook="x", new_hook="y", reason="why", citation="  ")
        with pytest.raises(LoopError, match="uncited"):
            apply_edits(NOTES, [bad])

    def test_unexplained_edit_refused(self) -> None:
        bad = RepairEdit(note="bakery-hours", old_hook="x", new_hook="y", reason="", citation="fail-1")
        with pytest.raises(LoopError, match="uncited|unexplained"):
            apply_edits(NOTES, [bad])


class TestHeldOutWall:
    def test_audit_raises_on_leak(self) -> None:
        leaked = [TASKS[0]["held_out"] + " sneaked into a prompt"]
        with pytest.raises(LoopError, match="leaked"):
            holdout_isolation_audit(leaked, TASKS)

    def test_repairer_inputs_pass_the_audit(self) -> None:
        gen0 = evaluate(NOTES, TASKS, "repair_visible", "gen0")
        failures = file_failures(gen0)
        visible = {t["id"]: t["repair_visible"] for t in TASKS}
        inputs = (
            [visible[f.task_id] + " " + f.observed for f in failures]
            + [NOTES[f.target].body for f in failures]
            + [NOTES[f.target].hook for f in failures]
        )
        holdout_isolation_audit(inputs, TASKS)  # must not raise

    def test_audit_is_punctuation_proof(self) -> None:
        stripped = TASKS[0]["held_out"].rstrip("?")
        with pytest.raises(LoopError, match="leaked"):
            holdout_isolation_audit([f"prompt containing {stripped} inside"], TASKS)

    def test_repaired_hooks_never_echo_visible_questions(self) -> None:
        gen0 = evaluate(NOTES, TASKS, "repair_visible", "gen0")
        failures = file_failures(gen0)
        for edit in repair(NOTES, failures):
            for t in TASKS:
                assert edit.new_hook.lower() != t["repair_visible"].lower()


class TestPlaceboBlindness:
    def test_placebo_is_a_function_of_notes_and_budget_only(self) -> None:
        a = placebo_edits(NOTES, budget=2)
        b = placebo_edits(NOTES, budget=2)
        assert a == b
        assert all(e.citation == "placebo-arm" for e in a)
        touched = {e.note for e in a}
        assert "town-history" not in touched and "civic-record" not in touched


class TestRegressionGate:
    def test_gate_reverts_a_breaking_edit(self) -> None:
        # The probe note's NAME shares no words with the task, so retrieval
        # depends entirely on the hook - the exact situation where a bad
        # repair can regress a previously-passing task.
        corpus = {
            "vendor-nine": Note("vendor-nine", "the blue lantern shop on Mill Lane", "memory", "Sells lanterns."),
        }
        tasks = [{
            "id": "probe-a", "relevant": "vendor-nine",
            "repair_visible": "where is the blue lantern shop",
            "held_out": "which shop on Mill Lane sells lanterns",
        }]
        sabotage = RepairEdit(
            note="vendor-nine", old_hook=corpus["vendor-nine"].hook,
            new_hook="misc", reason="sabotage probe", citation="probe-cite",
        )
        after, accepted, reverted = regression_gate(corpus, [sabotage], tasks)
        assert accepted == [] and len(reverted) == 1
        assert after["vendor-nine"].hook == "the blue lantern shop on Mill Lane"

    def test_gate_accepts_a_harmless_edit(self) -> None:
        gen0 = evaluate(NOTES, TASKS, "repair_visible", "gen0")
        edits = repair(NOTES, file_failures(gen0))
        _after, accepted, reverted = regression_gate(NOTES, edits, TASKS)
        assert len(accepted) == 2 and reverted == []


class TestFixtureShape:
    def test_two_lazy_hook_patients_miss_at_gen0(self) -> None:
        gen0 = evaluate(NOTES, TASKS, "repair_visible", "gen0")
        missed = {r.target for r in gen0.results if not r.hit}
        assert missed == {"town-history", "civic-record"}
        held0 = evaluate(NOTES, TASKS, "held_out", "gen0-frozen")
        assert held0.hits == 8 and held0.total == 10

    def test_failure_notes_are_valid_corpus_notes(self) -> None:
        from repairlab.loop import failure_note

        gen0 = evaluate(NOTES, TASKS, "repair_visible", "gen0")
        for record in file_failures(gen0):
            note = failure_note(record)
            assert parse_note(note.render()) == note
            assert note.kind == "failure"

    def test_failure_notes_never_pollute_retrieval(self) -> None:
        notes = dict(NOTES)
        notes["fail-t09"] = Note("fail-t09", "retrieval miss on town-history", "failure", "x")
        recalled = recall_names("retrieval miss on town history", notes)
        assert "fail-t09" not in recalled


def run_demo(workdir: Path) -> None:
    shutil.copytree(REPO / "src", workdir / "src")
    shutil.copytree(REPO / "fixtures", workdir / "fixtures")
    shutil.copy(REPO / "README.md", workdir / "README.md")
    result = subprocess.run(  # noqa: S603 - running our own module under test
        [sys.executable, "-m", "repairlab", "demo", "--quiet"],
        cwd=workdir, env={**os.environ, "PYTHONPATH": str(workdir / "src")},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def artifact_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for sub in ("wiki", "runs", "report"):
        out.extend(sorted(p for p in (root / sub).rglob("*") if p.is_file()))
    out.append(root / "metrics.jsonl")
    out.append(root / "README.md")
    return out


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    workdir = tmp_path_factory.mktemp("run_a")
    run_demo(workdir)
    return workdir


class TestPipeline:
    def test_ledger_has_citations_and_stop(self, demo_run: Path) -> None:
        entries = [
            json.loads(line)
            for line in (demo_run / "runs" / "repair-ledger.jsonl").read_text("utf-8").splitlines()
        ]
        accepts = [e for e in entries if e["action"] == "ACCEPT"]
        assert len(accepts) == 2 and all(e["citation"].startswith("fail-") for e in accepts)
        assert entries[-1]["action"] == "STOP" and entries[-1]["reason"].strip()

    def test_metrics_match_design(self, demo_run: Path) -> None:
        rows = [json.loads(x) for x in (demo_run / "metrics.jsonl").read_text("utf-8").splitlines()]
        arms = {(r["arm"], r["split"]): r for r in rows if r["kind"] == "arm"}
        assert arms[("gen0-frozen", "held_out")]["hits"] == 8
        assert arms[("repair", "held_out")]["hits"] == 10
        assert arms[("placebo", "held_out")]["hits"] == 8
        bloat = arms[("goodhart-bloat", "held_out")]
        assert bloat["index_tokens"] > arms[("repair", "held_out")]["index_tokens"]

    def test_no_wallclock_in_artifacts(self, demo_run: Path) -> None:
        for path in artifact_files(demo_run):
            for line in path.read_text("utf-8").splitlines():
                assert not WALLCLOCK_RE.search(line), f"{path.name}: {line[:60]}"


class TestDeterminism:
    def test_two_runs_byte_identical(self, demo_run: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
        second = tmp_path_factory.mktemp("run_b")
        run_demo(second)
        fa, fb = artifact_files(demo_run), artifact_files(second)
        assert [p.relative_to(demo_run) for p in fa] == [p.relative_to(second) for p in fb]
        for pa, pb in zip(fa, fb, strict=True):
            assert pa.read_bytes() == pb.read_bytes(), pa.name


class TestKeylessViaAst:
    FORBIDDEN = {"socket", "urllib", "http", "requests", "subprocess", "datetime", "time", "random"}

    def test_no_forbidden_imports(self) -> None:
        for path in sorted((REPO / "src" / "repairlab").glob("*.py")):
            tree = ast.parse(path.read_text("utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    tops = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    tops = {(node.module or "").split(".")[0]}
                else:
                    continue
                assert not tops & self.FORBIDDEN, path.name


class TestReadmePinned:
    README_TEXT = (REPO / "README.md").read_text(encoding="utf-8")

    def test_first_bolded_line_is_the_frame(self) -> None:
        assert self.README_TEXT.index("**The model never learns; the notes do.**") < 200

    def test_star_patient_and_wall_present(self) -> None:
        assert "assorted notes" in self.README_TEXT
        assert "sealed before generation zero" in self.README_TEXT
        assert "Loop 2" in self.README_TEXT

    def test_no_wallclock_in_readme(self) -> None:
        assert not WALLCLOCK_RE.search(self.README_TEXT)


class TestHygieneGate:
    def test_repo_passes_its_own_gate(self) -> None:
        result = subprocess.run(  # noqa: S603 - running our own tool under test
            [sys.executable, str(REPO / "tools" / "blocklist_check.py")],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stdout
