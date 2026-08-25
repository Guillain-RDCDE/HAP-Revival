#!/usr/bin/env python3
"""
Check every relative link and heading anchor in the project's Markdown.

The repository already runs markdownlint and a link checker, but neither looks
at **fragments**: `[text](../README.md#some-heading)` passes both while pointing
at a heading that no longer exists. Two such links had been silently dead since
a README rewrite two weeks earlier — this exists so that cannot happen again.

    python tools/check_links.py          # whole repo
    python tools/check_links.py docs/    # a subtree

Stdlib only. External URLs are ignored on purpose: they die for reasons outside
this repository and blocking on them would train everyone to ignore the check.
Exit code 0 if everything resolves, 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# [label](target) — target captured up to the closing paren.
LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


def anchor_for(heading_text: str) -> str:
    """Slugify a heading the way GitHub does.

    Inline markup is dropped, punctuation removed, spaces become hyphens.
    Close enough for our own documents; it is not a full CommonMark parser.
    """
    text = re.sub(r"`|\*|_|~", "", heading_text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)   # [label](url) -> label
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return text.strip().lower().replace(" ", "-")


def anchors_of(path: Path) -> set[str]:
    anchors: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return anchors
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if m:
            anchors.add(anchor_for(m.group(2)))
    return anchors


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.md")
        if not any(part in SKIP_DIRS for part in p.parts)
    )


def check(root: Path) -> list[str]:
    problems: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}

    for md in markdown_files(root):
        text = md.read_text(encoding="utf-8", errors="replace")
        for match in LINK.finditer(text):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#!")):
                continue
            file_part, _, fragment = target.partition("#")

            if file_part:
                dest = (md.parent / file_part).resolve()
                if not dest.exists():
                    problems.append(f"{md}: missing file -> {target}")
                    continue
            else:
                dest = md.resolve()          # same-document anchor

            if not fragment:
                continue
            if dest.suffix.lower() != ".md":
                continue                     # fragments into non-Markdown: not ours to judge
            if dest not in anchor_cache:
                anchor_cache[dest] = anchors_of(dest)
            if fragment not in anchor_cache[dest]:
                problems.append(f"{md}: dead anchor -> {target}")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "root", nargs="?", default=".", help="directory to scan (default: repo root)"
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr)
        return 1

    problems = check(root)
    count = len(markdown_files(root))
    if problems:
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} broken reference(s) across {count} Markdown files")
        return 1
    print(f"all relative links and anchors resolve ({count} Markdown files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
