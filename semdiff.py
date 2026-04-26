#!/usr/bin/env python3
"""semdiff — Semantic diff tool for markdown and text files.

Diffs two text or markdown files by structure (sections/paragraphs)
rather than raw lines, producing colored terminal output, HTML, or JSON.

Requirements: Python 3.9+, stdlib only.
"""

from __future__ import annotations

import argparse
import difflib
import html as html_mod
import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence


# ── Chunk model ──────────────────────────────────────────────────────────────

class ChunkKind(Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE_BLOCK = "code_block"
    LIST = "list"
    BLANK = "blank"


@dataclass
class Chunk:
    kind: ChunkKind
    text: str
    heading_level: int = 0  # 1-6 for headings, 0 otherwise
    start_line: int = 0

    def normalized(self, ignore_ws: bool = False) -> str:
        t = self.text
        if ignore_ws:
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n{2,}", "\n", t)
            t = t.strip()
        return t


# ── Chunker ──────────────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)]) ")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


def chunk_markdown(text: str) -> List[Chunk]:
    """Split *text* into semantic chunks (headings, paragraphs, code blocks, lists)."""
    lines = text.split("\n")
    chunks: List[Chunk] = []
    i = 0

    def _flush_paragraph(buf: list[str], start: int):
        body = "\n".join(buf)
        if body.strip():
            # Decide if it's a list
            if all(_LIST_RE.match(l) or not l.strip() for l in buf if l.strip()):
                chunks.append(Chunk(ChunkKind.LIST, body, start_line=start))
            else:
                chunks.append(Chunk(ChunkKind.PARAGRAPH, body, start_line=start))

    para_buf: list[str] = []
    para_start = 0

    while i < len(lines):
        line = lines[i]

        # ── code fence ───────────────────────────────────────────────────
        fence_m = _FENCE_RE.match(line)
        if fence_m:
            if para_buf:
                _flush_paragraph(para_buf, para_start)
                para_buf = []
            fence_char = fence_m.group(1)[0]
            fence_len = len(fence_m.group(1))
            code_lines = [line]
            code_start = i
            i += 1
            while i < len(lines):
                code_lines.append(lines[i])
                if re.match(rf"^{re.escape(fence_char)}{{{fence_len},}}$", lines[i].rstrip()):
                    i += 1
                    break
                i += 1
            chunks.append(Chunk(ChunkKind.CODE_BLOCK, "\n".join(code_lines), start_line=code_start))
            continue

        # ── heading ──────────────────────────────────────────────────────
        h_m = _HEADING_RE.match(line)
        if h_m:
            if para_buf:
                _flush_paragraph(para_buf, para_start)
                para_buf = []
            level = len(h_m.group(1))
            chunks.append(Chunk(ChunkKind.HEADING, line, heading_level=level, start_line=i))
            i += 1
            continue

        # ── blank line → flush paragraph ─────────────────────────────────
        if not line.strip():
            if para_buf:
                _flush_paragraph(para_buf, para_start)
                para_buf = []
            i += 1
            continue

        # ── accumulate paragraph / list ──────────────────────────────────
        if not para_buf:
            para_start = i
        para_buf.append(line)
        i += 1

    if para_buf:
        _flush_paragraph(para_buf, para_start)

    return chunks


# ── Diff engine ──────────────────────────────────────────────────────────────

class ChangeType(Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    EQUAL = "equal"


@dataclass
class Change:
    change_type: ChangeType
    old_chunk: Optional[Chunk] = None
    new_chunk: Optional[Chunk] = None
    similarity: float = 0.0  # 0-1 for modified chunks


def diff_chunks(
    old_chunks: List[Chunk],
    new_chunks: List[Chunk],
    ignore_ws: bool = False,
) -> List[Change]:
    """Align and diff two chunk lists using SequenceMatcher."""
    old_texts = [c.normalized(ignore_ws) for c in old_chunks]
    new_texts = [c.normalized(ignore_ws) for c in new_chunks]

    sm = difflib.SequenceMatcher(None, old_texts, new_texts, autojunk=False)
    changes: List[Change] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                changes.append(Change(ChangeType.EQUAL, old_chunks[i1 + k], new_chunks[j1 + k], similarity=1.0))
        elif tag == "replace":
            # Pair them up; leftovers are add/remove
            olen = i2 - i1
            nlen = j2 - j1
            paired = min(olen, nlen)
            for k in range(paired):
                oc = old_chunks[i1 + k]
                nc = new_chunks[j1 + k]
                ratio = difflib.SequenceMatcher(
                    None, oc.normalized(ignore_ws), nc.normalized(ignore_ws)
                ).ratio()
                changes.append(Change(ChangeType.MODIFIED, oc, nc, similarity=ratio))
            for k in range(paired, olen):
                changes.append(Change(ChangeType.REMOVED, old_chunks[i1 + k]))
            for k in range(paired, nlen):
                changes.append(Change(ChangeType.ADDED, new_chunk=new_chunks[j1 + k]))
        elif tag == "delete":
            for k in range(i1, i2):
                changes.append(Change(ChangeType.REMOVED, old_chunks[k]))
        elif tag == "insert":
            for k in range(j1, j2):
                changes.append(Change(ChangeType.ADDED, new_chunk=new_chunks[k]))

    return changes


# ── Summary ──────────────────────────────────────────────────────────────────

@dataclass
class Summary:
    added: int = 0
    removed: int = 0
    modified: int = 0

    def line(self) -> str:
        return f"+{self.added} added, -{self.removed} removed, ~{self.modified} modified sections"


def summarize(changes: List[Change]) -> Summary:
    s = Summary()
    for c in changes:
        if c.change_type == ChangeType.ADDED:
            s.added += 1
        elif c.change_type == ChangeType.REMOVED:
            s.removed += 1
        elif c.change_type == ChangeType.MODIFIED:
            s.modified += 1
    return s


# ── Terminal output ──────────────────────────────────────────────────────────

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _inline_diff(old_text: str, new_text: str) -> str:
    """Show line-level sub-diff inside a modified chunk."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    result: list[str] = []
    for line in difflib.unified_diff(old_lines, new_lines, lineterm=""):
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            result.append(f"{_GREEN}+{line[1:]}{_RESET}")
        elif line.startswith("-"):
            result.append(f"{_RED}-{line[1:]}{_RESET}")
        else:
            result.append(f" {line[1:]}" if line.startswith(" ") else line)
    return "".join(result).rstrip("\n")


def render_terminal(changes: List[Change]) -> str:
    s = summarize(changes)
    parts: list[str] = [f"{_BOLD}{s.line()}{_RESET}", ""]

    for c in changes:
        if c.change_type == ChangeType.EQUAL:
            continue
        if c.change_type == ChangeType.ADDED:
            assert c.new_chunk is not None
            label = f"[{c.new_chunk.kind.value}]"
            parts.append(f"{_GREEN}+ {label}{_RESET}")
            for ln in c.new_chunk.text.splitlines():
                parts.append(f"{_GREEN}+  {ln}{_RESET}")
            parts.append("")
        elif c.change_type == ChangeType.REMOVED:
            assert c.old_chunk is not None
            label = f"[{c.old_chunk.kind.value}]"
            parts.append(f"{_RED}- {label}{_RESET}")
            for ln in c.old_chunk.text.splitlines():
                parts.append(f"{_RED}-  {ln}{_RESET}")
            parts.append("")
        elif c.change_type == ChangeType.MODIFIED:
            assert c.old_chunk is not None and c.new_chunk is not None
            label = f"[{c.new_chunk.kind.value}]"
            sim_pct = int(c.similarity * 100)
            parts.append(f"{_YELLOW}~ {label} ({sim_pct}% similar){_RESET}")
            parts.append(_inline_diff(c.old_chunk.text, c.new_chunk.text))
            parts.append("")

    return "\n".join(parts)


# ── HTML output ──────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>semdiff</title>
<style>
body {{ font-family: monospace; margin: 2em; background: #1e1e2e; color: #cdd6f4; }}
.summary {{ font-size: 1.1em; margin-bottom: 1em; font-weight: bold; }}
.chunk {{ margin-bottom: 1em; padding: 0.5em; border-radius: 4px; white-space: pre-wrap; }}
.added {{ background: #1a3d1f; color: #a6e3a1; }}
.removed {{ background: #3d1a1a; color: #f38ba8; }}
.modified {{ background: #3d3a1a; color: #f9e2af; }}
.diff-add {{ color: #a6e3a1; }}
.diff-del {{ color: #f38ba8; }}
</style></head><body>
<h1>semdiff</h1>
<div class="summary">{summary}</div>
{body}
</body></html>"""


def render_html(changes: List[Change]) -> str:
    s = summarize(changes)
    parts: list[str] = []
    for c in changes:
        if c.change_type == ChangeType.EQUAL:
            continue
        if c.change_type == ChangeType.ADDED:
            assert c.new_chunk is not None
            parts.append(
                f'<div class="chunk added"><strong>+ [{c.new_chunk.kind.value}]</strong>\n'
                f"{html_mod.escape(c.new_chunk.text)}</div>"
            )
        elif c.change_type == ChangeType.REMOVED:
            assert c.old_chunk is not None
            parts.append(
                f'<div class="chunk removed"><strong>- [{c.old_chunk.kind.value}]</strong>\n'
                f"{html_mod.escape(c.old_chunk.text)}</div>"
            )
        elif c.change_type == ChangeType.MODIFIED:
            assert c.old_chunk is not None and c.new_chunk is not None
            sim_pct = int(c.similarity * 100)
            old_lines = c.old_chunk.text.splitlines(keepends=True)
            new_lines = c.new_chunk.text.splitlines(keepends=True)
            diff_html: list[str] = []
            for line in difflib.unified_diff(old_lines, new_lines, lineterm=""):
                if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
                    continue
                esc = html_mod.escape(line[1:] if len(line) > 1 else "")
                if line.startswith("+"):
                    diff_html.append(f'<span class="diff-add">+{esc}</span>')
                elif line.startswith("-"):
                    diff_html.append(f'<span class="diff-del">-{esc}</span>')
                else:
                    diff_html.append(f" {esc}")
            parts.append(
                f'<div class="chunk modified"><strong>~ [{c.new_chunk.kind.value}] ({sim_pct}% similar)</strong>\n'
                + "\n".join(diff_html)
                + "</div>"
            )
    return _HTML_TEMPLATE.format(summary=html_mod.escape(s.line()), body="\n".join(parts))


# ── JSON output ──────────────────────────────────────────────────────────────

def render_json(changes: List[Change]) -> str:
    s = summarize(changes)
    out: list[dict] = []
    for c in changes:
        if c.change_type == ChangeType.EQUAL:
            continue
        entry: dict = {"type": c.change_type.value}
        if c.old_chunk:
            entry["old"] = {"kind": c.old_chunk.kind.value, "text": c.old_chunk.text, "heading_level": c.old_chunk.heading_level}
        if c.new_chunk:
            entry["new"] = {"kind": c.new_chunk.kind.value, "text": c.new_chunk.text, "heading_level": c.new_chunk.heading_level}
        if c.change_type == ChangeType.MODIFIED:
            entry["similarity"] = round(c.similarity, 4)
        out.append(entry)
    return json.dumps({"summary": {"added": s.added, "removed": s.removed, "modified": s.modified}, "changes": out}, indent=2)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="semdiff",
        description="Semantic diff for markdown and text files.",
    )
    parser.add_argument("file_a", help="Original file")
    parser.add_argument("file_b", help="Modified file")
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--html", action="store_true", help="Output self-contained HTML diff")
    fmt.add_argument("--json", action="store_true", help="Output JSON diff")
    parser.add_argument("--ignore-whitespace", action="store_true", help="Normalize whitespace before comparing")
    parser.add_argument("--stats-only", action="store_true", help="Print summary only, no diff body")
    args = parser.parse_args(argv)

    try:
        text_a = open(args.file_a, encoding="utf-8").read()
    except FileNotFoundError:
        print(f"semdiff: error: file not found: {args.file_a}", file=sys.stderr)
        return 1
    try:
        text_b = open(args.file_b, encoding="utf-8").read()
    except FileNotFoundError:
        print(f"semdiff: error: file not found: {args.file_b}", file=sys.stderr)
        return 1

    chunks_a = chunk_markdown(text_a)
    chunks_b = chunk_markdown(text_b)
    changes = diff_chunks(chunks_a, chunks_b, ignore_ws=args.ignore_whitespace)
    s = summarize(changes)

    if args.stats_only:
        print(s.line())
        return 0

    if args.html:
        print(render_html(changes))
    elif args.json:
        print(render_json(changes))
    else:
        print(render_terminal(changes))

    return 0


if __name__ == "__main__":
    sys.exit(main())
