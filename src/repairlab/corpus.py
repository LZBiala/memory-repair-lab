"""The memory substrate: markdown notes, an index, and the lexical scorer.

This repo is the control loop that closes over the memory layer of its parent
project (wiki-memory-lab). The substrate here is deliberately minimal and
re-implemented fresh: one note per concept with strict two-field frontmatter
plus a kind marker, a one-line-per-note index, and the same dumb-on-purpose
lexical scorer family (name words double, hook words single, no stemming) —
so a lazy hook fails retrieval for a reason anyone can read.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

DELIM = "---"
TOP_K = 3
MIN_SCORE = 2
NAME_WEIGHT = 2
HOOK_WEIGHT = 1

_WORD_RE = re.compile(r"[a-z0-9']+")
STOPWORDS = frozenset(
    (
        "a an and are at by can do does for from how i in is it of on or the to "
        "was what when where which who will you your"
    ).split()
)


class CorpusError(ValueError):
    """Raised when a note does not conform."""


@dataclass(frozen=True)
class Note:
    name: str
    hook: str
    kind: str  # "memory" | "failure"
    body: str

    def render(self) -> str:
        return "\n".join(
            [
                DELIM,
                f"name: {self.name}",
                f"hook: {self.hook}",
                f"kind: {self.kind}",
                DELIM,
                "",
                self.body.rstrip("\n"),
                "",
            ]
        )


def parse_note(text: str) -> Note:
    lines = text.split("\n")
    if not lines or lines[0] != DELIM:
        raise CorpusError("note must start with '---'")
    try:
        end = lines.index(DELIM, 1)
    except ValueError as exc:
        raise CorpusError("unterminated frontmatter") from exc
    fields: dict[str, str] = {}
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        key, sep, value = raw.partition(":")
        if not sep or key.strip() not in ("name", "hook", "kind"):
            raise CorpusError(f"bad frontmatter line: {raw!r}")
        if key.strip() in fields:
            raise CorpusError(f"duplicate key {key.strip()!r}")
        fields[key.strip()] = value.strip()
    for required in ("name", "hook", "kind"):
        if required not in fields:
            raise CorpusError(f"missing key {required!r}")
    if fields["kind"] not in ("memory", "failure"):
        raise CorpusError(f"unknown kind {fields['kind']!r}")
    body = "\n".join(lines[end + 1 :]).strip("\n")
    return Note(name=fields["name"], hook=fields["hook"], kind=fields["kind"], body=body)


def words(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(text.lower())) - STOPWORDS


def score(task_text: str, note: Note) -> int:
    task_words = words(task_text)
    name_words = words(note.name.replace("-", " "))
    hook_words = words(note.hook) - name_words
    return NAME_WEIGHT * len(task_words & name_words) + HOOK_WEIGHT * len(
        task_words & hook_words
    )


def recall_names(task_text: str, notes: dict[str, Note]) -> list[str]:
    """Top-k memory-note names: score desc, then name asc. Failure notes are
    never retrieval candidates — the loop's bookkeeping must not pollute the
    memory it repairs."""
    scored = [
        (score(task_text, n), name)
        for name, n in notes.items()
        if n.kind == "memory"
    ]
    eligible = sorted(
        [(s, name) for s, name in scored if s >= MIN_SCORE],
        key=lambda pair: (-pair[0], pair[1]),
    )
    return [name for _, name in eligible[:TOP_K]]


def index_text(notes: dict[str, Note]) -> str:
    lines = ["# index", ""]
    for name in sorted(notes):
        if notes[name].kind == "memory":
            lines.append(f"- [[{name}]] — {notes[name].hook}")
    return "\n".join(lines) + "\n"


def proxy_tokens(text: str) -> int:
    return math.ceil(len(text) / 4) if text else 0
