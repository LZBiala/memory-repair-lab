# Contributing

Thanks for looking. This repo is small on purpose; contributions that keep it
small, honest, and regenerable are welcome.

## Setup

```
git clone https://github.com/LZBiala/memory-repair-lab
cd memory-repair-lab
pip install -e ".[dev]"   # runtime is stdlib-only; the dev extra is pytest
python -m repairlab demo
```

## Before you open a PR

Run the same sequence CI runs (Windows and Linux, pinned Python 3.12,
zero secrets):

```
pytest -q                          # contract suite
python tools/blocklist_check.py    # hygiene gate
python -m repairlab demo --quiet   # regenerate every published artifact
git diff --exit-code               # fail on any drift
```

If `git diff` is not clean after regeneration, either commit the regenerated
artifacts with your change or your change broke a claim - read the diff and
decide which.

## What PRs are welcome

- **New defect classes** in the fixture corpus - the current one plants lazy
  hooks; other realistic ways notes fail to retrieve are worth having,
  each with task pairs (visible/held-out) that exercise it.
- **New tasks** for the existing corpus, always as sealed visible/held-out
  pairs - never a held-out phrasing that echoes the visible one.
- **New probes and contract tests** - anything that checks the loop's rules
  hold (citation discipline, the held-out wall, placebo blindness, gate
  behavior) is more valuable than anything that adds capability.
- Fixes to the walkthrough or docs where something is unclear.

Deterministic changes only in the measured path: the published numbers must
come out identical on every machine.

## House law

Every published number must regenerate in CI - the build fails if a claim
drifts. Live-model results never enter drift-gated sections. The hygiene
gate must pass.

Practical corollaries: never edit between the AUTOGEN markers in README.md
by hand - `report.py` renders that block and CI fails on mismatch. If you
bring your own repairer through the `repair()` seam, its results go on
dated pages with run counts and variance, not in the README.
