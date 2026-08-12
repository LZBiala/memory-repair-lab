"""The walkthrough page is quoted-and-TESTED, family law: every replay beat
must be a line the demo actually streams, and the headline numbers must match
the committed metrics.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HTML = (REPO / "docs" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def demo_stream(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Run the demo in-process on a temp copy, capturing the streamed lines."""
    import repairlab.__main__ as main_mod

    tmp = tmp_path_factory.mktemp("stream")
    shutil.copytree(REPO / "fixtures", tmp / "fixtures")
    shutil.copy(REPO / "README.md", tmp / "README.md")
    originals = {
        name: getattr(main_mod, name)
        for name in ("FIXTURE", "README", "WIKI_DIR", "RUNS_DIR", "REPORT_DIR", "METRICS")
    }
    try:
        main_mod.FIXTURE = tmp / "fixtures" / "corpus.json"
        main_mod.README = tmp / "README.md"
        main_mod.WIKI_DIR = tmp / "wiki"
        main_mod.RUNS_DIR = tmp / "runs"
        main_mod.REPORT_DIR = tmp / "report"
        main_mod.METRICS = tmp / "metrics.jsonl"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            assert main_mod.demo(quiet=False) == 0
        return buffer.getvalue()
    finally:
        for name, value in originals.items():
            setattr(main_mod, name, value)


class TestBeatsAreVerbatim:
    def test_every_beat_is_a_streamed_line(self, demo_stream: str) -> None:
        lines = re.findall(r'\bline: "((?:[^"\\]|\\.)*)"', HTML)
        assert len(lines) >= 8
        for raw in lines:
            line = raw.replace('\\"', '"')
            assert line in demo_stream, line[:70]

    def test_beat_count_matches_copy(self) -> None:
        n = len(re.findall(r'\bline: "', HTML))
        words = {7: "Seven", 8: "Eight", 9: "Nine"}
        assert f"{words[n]} beats" in HTML


class TestHeadlineNumbers:
    def test_arm_numbers_match_metrics(self) -> None:
        rows = [
            json.loads(x)
            for x in (REPO / "metrics.jsonl").read_text("utf-8").splitlines()
        ]
        arms = {(r["arm"], r["split"]): r for r in rows if r["kind"] == "arm"}
        gen0 = arms[("gen0-frozen", "held_out")]
        mend = arms[("repair", "held_out")]
        pla = arms[("placebo", "held_out")]
        assert f"<b>{gen0['hits']}/{gen0['total']}</b>" in HTML
        assert f"<b>{mend['hits']}/{mend['total']}</b>" in HTML
        assert f"<b>{pla['hits']}/{pla['total']}</b>" in HTML

    def test_honest_section_present(self) -> None:
        assert "Loop 2" in HTML
        assert "never model capability" in HTML


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
