# memory-repair-lab

![generations](report/generations.svg)

**The model never learns; the notes do.** A memory-repair loop built on the
memory layer of [wiki-memory-lab](https://github.com/LZBiala/wiki-memory-lab):
when a note can't be found, that miss is written down; a repair pass
relabels notes, each fix naming the miss that caused it; and results are
re-scored on a quiz **sealed in an envelope before any fixing began** -
plus a sugar-pill (placebo) arm, a re-check gate, and a published demo of
how the score can be gamed.

## What this is

A small Python program that gives a scripted helper (no language model anywhere in it) a memory made of plain text files: one note per topic, plus an index with one line per note. It replays 8 scripted sessions of errands in a made-up town (~20 tasks), counts what reading that memory costs, and checks whether its filing rules fire when they should. It measures the filing system, not any model.

## Why it matters

AI assistants either forget everything between chats or reread their whole diary before every answer. Rereading costs money, because providers bill for every piece of text sent in. And when the memory is stored in a form a person cannot open and read, nobody can check what the assistant believes or why it dropped something. This repo counts whether reading an index and a few notes costs less than rereading everything, shows a memory small enough that it does not, and makes every deletion leave a written reason.

## Quickstart (three commands, no keys)

```
git clone https://github.com/LZBiala/wiki-memory-lab && cd wiki-memory-lab
pip install -e .
python -m wikimemlab demo
```

No API keys (no account with any AI service). The program needs nothing outside Python's standard library; its dependency list in `pyproject.toml` is empty. The demo prints each session as it runs, then points you at `wiki/` (the memory, plain markdown), `runs/` (the session transcripts, every memory operation with its written reason), `report/hero.svg` (the token chart) and `metrics.jsonl` (every published number). Three runs timed by hand on one Windows machine each finished in under a second; that is a stopwatch reading, not a benchmark, and the repo does not check it. What the repo does check: a fresh run leaves every committed file unchanged, byte for byte (`git diff --exit-code`, run by CI, the automated check on every push, on Windows and Linux).

## How it works

Picture a recipe box with an index card on top. Each recipe is a note. The card lists every note's title and a one-line hook (its summary). At the start of a session the helper reads only the card. For each question it counts the exact words each card line shares with the question (a word from the note's title counts double), keeps the lines scoring at least 2, and pulls at most three notes. Exact words only: "park" does not match "parking". A new fact joins an existing note when the two titles match after lowercasing and hyphenating (extend-before-create); a paraphrased title creates a duplicate instead, and the harness (the test rig around the helper) counts that as an error rather than hiding it. A note shown to be wrong is archived only with a written reason (prune); the code refuses an empty one. A note neither created nor recalled for 5 sessions is archived automatically (decay).

Here is what that looks like in a real transcript, quoted from `runs/milldale-session_06.md`, a generated file that a test checks against this excerpt word for word:

```
## task s6t3 - "Can I still catch the route 4 bus by the square tonight?"
RECALL: bus-schedule (1 note(s) / 53 tokens)
ANSWER: No - the town notice posted today says route 4 is discontinued; a new
route 7 now runs from the square. [...]
WRITE-BACK: CREATE walk-in-clinic-hours - same clinic as the existing note - a
paraphrased title the exact matcher will miss, counted as false-CREATE
[intended EXTEND - counted as false-CREATE]

CORRECTION: PRUNE bus-schedule - contradicted by session 6 town notice: route 4 discontinued
CORRECTION: CREATE bus-route-7 - replacement for pruned bus-schedule
DECAY: ARCHIVE school-play - not created or recalled inside the decay window
```

The analogy holds in both directions. A big box makes the card worth reading first. A tiny box, where most questions need most recipes anyway, makes the card pure overhead. The numbers below show both.

## In plain English: what the numbers mean

A token is the unit AI providers bill by. This repo uses proxy tokens: characters divided by four, rounded up, a common rule of thumb and not any vendor's real count. The numbers below are copied by hand from the claims table further down; that table is regenerated from `metrics.jsonl` on every change, and CI fails the build if it drifts. If a number here ever disagrees with the table, the table is right.

- Cost. Reading the index first and then only the matching notes cost 2236 proxy tokens over the 8 sessions; loading every note every session cost 3654. The ratio, 0.61, is the claim; the absolute counts are not, because they depend on how many notes exist and how many each question touches. Both runs read the same notes (the load-everything run replays the exact wiki that existed at the start of each session) with the same scripted helper, so this grades a loading rule, not a model.
- Where it loses. On a separate 8-note mini corpus (corpus: the set of notes) built so its questions touch most of the notes, the method lost: 431 proxy tokens against 340 (ratio 1.27), measured at the last of its 2 sessions, the only one that reads memory. Published on purpose: the index is a fixed fee paid every session, and on a small memory where you need most notes anyway, that fee is pure loss.
- Retrieval. Precision 0.95 and recall 0.95: of the 21 notes the helper pulled, 20 were on the author's list of which notes each question needs (precision); of the 21 notes on that list, 20 were pulled (recall). The one wrong pull is a parking note that shares words with a park question. The one miss is a note given a deliberately lazy hook, "assorted notes", to show what a bad hook costs. Both numbers are an upper bound by construction: the same author wrote the questions, the hooks, and the list, so they measure how well the author's hooks fit the author's questions, not how the method fares on text someone else wrote.
- Filing rules. Counted from the operations log of one deterministic run (same input, same output, every time): 18 notes created, 1 extended, 2 pruned with a reason, 1 archived by decay, 21 recalls; 1 false-CREATE (the paraphrased duplicate in the transcript above) and 0 false-EXTENDs. This proves the harness enforces the rules and shows where the title matcher fails. It says nothing about whether a live model would follow the rules unprompted; the helper is scripted.

## What it does not show

The helper is scripted: its answers come from the fixture file (the script of sessions it replays) and its filing decisions follow rules. So this repo never publishes a "task completion" score, because here a task would count as done exactly when the right note was pulled, so a completion score would only restate the retrieval score. What the repo can measure honestly is the memory protocol itself: the token arithmetic, how well one-line hooks retrieve labeled notes, and whether the rules fire when they should, including the two ways the title matcher fails. Whether a live model would keep this discipline unprompted is untested here.

## Try your own case

Add a task to `fixtures/milldale/sessions.json` (each task has an id, a question, the notes it needs, the scripted answer, and any facts to file), rerun the demo, and read `runs/` and `metrics.jsonl`. Whichever way the numbers move, they get published. Before proposing the change, run the gate sequence in `CONTRIBUTING.md`: the test suite, `python tools/blocklist_check.py` (scans for private paths, email addresses, and a hashed list of banned words), the regeneration, and `git diff --exit-code`. One test pins the task count written in this README to the fixture, so that number must move with it, and the regenerated files are committed in the same change.

---

## For engineers

Everything below is the original technical README: the design, the measurements, and how to reproduce them.

> **Every measured number below regenerates in CI with zero API keys - if a
> claim drifts, the build fails.** (`pytest` → hygiene gate → full run →
> `git diff --exit-code`, Windows and Linux.) The repairer is a deterministic
> script: these numbers prove the *loop* and the value of the *failure
> signal*, never model capability. The hygiene gate itself bans this repo's
> tempting overclaims - CI refuses the marketing.

## The idea in 30 seconds

Imagine a recipe box that keeps a second stack of cards: every time a recipe
couldn't be found when dinner needed it, a **mistake-card** gets written saying
exactly what went wrong. Later, someone sits down with only those
mistake-cards and fixes the index tabs - better labels, citing the mistake
that demanded each fix. Then they re-test with a quiz **sealed in an envelope
before the fixing started**, so they can't fool themselves. The cook never
gets smarter - the box gets easier to use, every fix has its reason stapled to
it, and the envelope keeps everyone honest.

## In plain English

The mistake-cards above, scored: finding notes went from 8 out of 10 to 10 out
of 10 after one repair round, graded on the quiz sealed before any fixing
began. The proof it wasn't luck: a sugar-pill run made the same number of
edits without reading the mistake-cards and stayed at 8 out of 10 - the
failure reports did the work, not the busywork. Every accepted fix names the
exact mistake that caused it, and the repo says out loud what it does not
prove.

## The agentic graph

A few separate jobs take turns tending one shared box of notes - and every
hand-off between them is a plain file you can open in an editor:

```
MEMORY (wiki notes) --index--> EVALUATOR --misses--> FAILURE RECORDS
FAILURE RECORDS --citations--> REPAIRER --candidate edits--> GATES
GATES (regression replay + citation check) --accepted diffs--> MEMORY
```

Family rules apply: roles are structurally separated; the repairer may read
ONLY failure records and target note bodies (**a test asserts held-out task
text never enters its input**); the gates alone decide what lands; and the
ledger refuses any edit without a written reason *and* a citation. The
placebo arm runs the same budget with the failure-record edge **cut** -
separating "the failure signal helps" from "any editing helps."

## Quickstart (no keys)

```
git clone https://github.com/LZBiala/memory-repair-lab
cd memory-repair-lab
pip install -e .          # installs nothing but this package - runtime is stdlib-only
python -m repairlab demo
```

Watch generation 0 miss the two lazy-hook notes, the failures get filed, the
cited repairs land through the gate, and the held-out re-measurement - then
open `runs/repair-ledger.jsonl` and read every decision with its reason.

## The star patient

The fixture wiki inherits its parent's most famous defect: a note whose hook
is just `assorted notes`. Generation 0 cannot retrieve it - the hook gives
the scorer nothing. The repairer, reading only the failure record and the
note's own body, rewrites the hook **from the note's first line** (content-
derived, never copied from the visible question - so the held-out phrasing
can only be won by genuinely better metadata). One generation later, both
phrasings retrieve it. The fix is a one-line diff citing `fail-t09`, in the
open, in the ledger.

## Claims, retested on every change (SLO-style)

Rendered from `metrics.jsonl` by `report.py` - no measured number below is
typed by hand, and CI fails if regeneration disagrees.

<!-- AUTOGEN:BEGIN - rendered by report.py from metrics.jsonl; do not edit by hand -->

| claim | number (regenerated by CI) | how measured | honest caveat |
|---|---|---|---|
| Cited repairs improve HELD-OUT recall | **8/10 → 10/10 held-out hits (precision 0.80 → 0.83) after one repair generation** | held-out phrasings sealed before generation zero (repair-visible = the fit split); a test asserts they never enter repairer input; frozen gen-0 replayed in the same run | scripted repairer on author-labeled fixtures - proves the loop, an upper bound by construction, never model capability |
| The failure signal - not editing - does the work | **placebo arm (same edit budget, blind): 8/10 - unchanged from gen-0** | identical budget; placebo edits computed without reading failure records | one corpus, one deterministic churn rule; the arm separates signal from motion, nothing more |
| Every accepted edit cites its failure record | **2 accepted edits, 2/2 cited; 0 reverted by the regression gate** | the protocol refuses uncited edits; the full suite replays after every acceptance | conformance of the loop, labeled as such |
| Gaming recall has a visible price (the Goodhart demo) | **hook-bloat arm: 10/10 held-out hits at index cost 215 tok vs repair arm 10/10 at 185 tok** | an authored strategy committed and measured beside the honest one; proxy tokens = chars/4 | a demonstration of a failure mode, not evidence any real improver behaves this way |
| One repair generation, stated as such | **stop label: no remaining repair-visible failures after generation 1** | the demo runs exactly ONE repair pass by construction; the label distinguishes done from budget-exhausted | 'termination' here is structural, not an enforced property - a real multi-generation loop with a K-cycle no-gain stop is Loop 2 work |

<!-- AUTOGEN:END -->

Regenerate everything yourself: `python -m repairlab demo --quiet && git diff`.

## Verification the worker cannot skip

Three gates stand between a candidate edit and the wiki: the regression
replay (every accepted edit re-runs the full suite), the citation check (an
edit that cannot name the failure record that motivated it does not land),
and the sealed held-out wall (the re-measurement uses phrasings frozen
before generation zero). None of them ask the repairer to be trustworthy -
they ask it to survive being checked. That is the pattern worth naming:
build the tools that verify the work, rather than trust the worker to have
done it well. The 8/10 → 10/10 held-out gain above is what one repair pass
looks like once it has to clear all three gates. The placebo arm is the
control that tells you what the gates alone are worth - same budget, same
churn, failure records withheld, and it stays flat at 8/10: the placebo arm
shows the FAILURE SIGNAL, not the churn, carries the value. The gates do not
manufacture that gain; they only make sure nothing gets credit for it that
did not earn it.

## What this does NOT show

The repairer is a deterministic rule. A scripted repairer fixing planted-style
failures proves that **the loop works and the failure signal carries value**
(the placebo arm, same budget and blind, fixes nothing) - it proves nothing
about any model's ability to reflect. "Recursive" in the strict sense -
repair policies that are themselves notes subject to repair - is **Loop 2**,
documented future work, not marketed until it exists in code. Held-out gains
here are upper bounds on author-labeled fixtures; a plateau on this corpus
says nothing about other corpora; and the model's weights never change - every
gain is attributable to a diffable text artifact in `git log -p`.

## Bring your own repairer (v1.1 seam)

The `repair()` seam accepts any function from failure records to cited edits.
A live-model repairer's results belong on dated pages with run counts and
variance - **never in this README**. Watch for: citation discipline (an edit
that can't name its failure is a guess), the regression gate (models love
collateral edits), and the held-out wall (echoing the visible question into a
hook is memorization wearing a fix's clothes).

## The family stack

Memory layer ([wiki-memory-lab](https://github.com/LZBiala/wiki-memory-lab)) →
evaluation layer ([agent-mutation-lab](https://github.com/LZBiala/agent-mutation-lab)) →
decision-calibration layer ([adversarial-chambers](https://github.com/LZBiala/adversarial-chambers)) →
**this repo: the control loop that closes over the memory layer.** An
architecture map, not a benchmark. Same laws everywhere: committed artifacts
ARE the claims; losses publish above the fold; every deletion carries its
reason.

## Repo map, tests, CI

```
src/repairlab/    corpus (notes/index/scorer), loop (failures, repair, placebo, gates), report
fixtures/         corpus.json - 10 Milldale notes (2 lazy hooks) + 10 task pairs (visible/held-out)
wiki/ runs/ report/ metrics.jsonl   - generated artifacts, committed on purpose
tests/            loop contracts (citation, held-out wall, placebo blindness, gate probe), determinism
tools/            blocklist_check.py - hygiene gate (first commit; bans this repo's own overclaims)
docs/             the interactive walkthrough page
```

CI: pytest → hygiene gate → full regeneration → `git diff --exit-code`,
Windows + Linux, pinned Python, zero secrets.

## Field notes (2026)

In research terms the placebo arm is a control group, and the sealed quiz
answers a known worry (the "Oracle ceiling"): finding the right note does
not guarantee acting on it correctly. Public
surveys of memory frameworks (further reading:
[a survey of agent memory frameworks](https://www.graphlit.com/blog/survey-of-ai-agent-memory-frameworks))
show controlled repair trials remain rare; this repo is a minimal,
fully-regenerable instance.

## Roadmap

Future work - stated as such, none of it in code yet:

- **Oracle-ceiling experiment:** measure whether repaired notes change
  downstream *actions*, not just retrieval hits. Any live-model runs will be
  published as a separate, labeled study with k-run variance - never inside
  the CI-gated claims above.
- **Pre/post context evals:** lint and clarity checks around each repair, so
  repair quality is instrumented, not assumed.

## License

MIT.
