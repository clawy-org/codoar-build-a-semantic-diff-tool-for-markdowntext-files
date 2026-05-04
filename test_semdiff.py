#!/usr/bin/env python3
"""Tests for semdiff — semantic diff tool for markdown/text files."""

import json
import textwrap
import pytest

from semdiff import (
    Chunk, ChunkKind, ChangeType,
    chunk_markdown, diff_chunks, summarize,
    render_terminal, render_html, render_json, main,
)


# ── Chunker tests ────────────────────────────────────────────────────────────

class TestChunkMarkdown:
    def test_heading(self):
        chunks = chunk_markdown("# Title\n\nSome text.")
        assert chunks[0].kind == ChunkKind.HEADING
        assert chunks[0].heading_level == 1
        assert chunks[1].kind == ChunkKind.PARAGRAPH

    def test_multiple_headings(self):
        md = "# H1\n\n## H2\n\n### H3"
        chunks = chunk_markdown(md)
        levels = [c.heading_level for c in chunks if c.kind == ChunkKind.HEADING]
        assert levels == [1, 2, 3]

    def test_code_block(self):
        md = "Text before\n\n```python\nprint('hi')\n```\n\nText after"
        chunks = chunk_markdown(md)
        kinds = [c.kind for c in chunks]
        assert ChunkKind.CODE_BLOCK in kinds
        code = [c for c in chunks if c.kind == ChunkKind.CODE_BLOCK][0]
        assert "print('hi')" in code.text

    def test_tilde_code_block(self):
        md = "~~~\ncode here\n~~~"
        chunks = chunk_markdown(md)
        assert any(c.kind == ChunkKind.CODE_BLOCK for c in chunks)

    def test_list_detection(self):
        md = "- item one\n- item two\n- item three"
        chunks = chunk_markdown(md)
        assert any(c.kind == ChunkKind.LIST for c in chunks)

    def test_numbered_list(self):
        md = "1. first\n2. second\n3. third"
        chunks = chunk_markdown(md)
        assert any(c.kind == ChunkKind.LIST for c in chunks)

    def test_empty_input(self):
        assert chunk_markdown("") == []

    def test_only_whitespace(self):
        assert chunk_markdown("   \n  \n   ") == []

    def test_paragraph_split_on_blank_line(self):
        md = "First paragraph.\n\nSecond paragraph."
        chunks = chunk_markdown(md)
        paras = [c for c in chunks if c.kind == ChunkKind.PARAGRAPH]
        assert len(paras) == 2


# ── Diff engine tests ────────────────────────────────────────────────────────

class TestDiffChunks:
    def test_identical_files(self):
        text = "# Hello\n\nWorld"
        a = chunk_markdown(text)
        b = chunk_markdown(text)
        changes = diff_chunks(a, b)
        s = summarize(changes)
        assert s.added == 0 and s.removed == 0 and s.modified == 0

    def test_fully_different(self):
        a = chunk_markdown("# Old\n\nOld text")
        b = chunk_markdown("# New\n\nNew text")
        changes = diff_chunks(a, b)
        s = summarize(changes)
        assert s.modified == 2  # heading + paragraph both changed

    def test_added_section(self):
        a = chunk_markdown("# Title\n\nPara one")
        b = chunk_markdown("# Title\n\nPara one\n\nPara two")
        changes = diff_chunks(a, b)
        s = summarize(changes)
        assert s.added == 1 and s.removed == 0 and s.modified == 0

    def test_removed_section(self):
        a = chunk_markdown("# Title\n\nPara one\n\nPara two")
        b = chunk_markdown("# Title\n\nPara one")
        changes = diff_chunks(a, b)
        s = summarize(changes)
        assert s.removed == 1

    def test_partial_edit(self):
        a = chunk_markdown("# Title\n\nThe quick brown fox jumps over the lazy dog.")
        b = chunk_markdown("# Title\n\nThe quick brown cat jumps over the lazy dog.")
        changes = diff_chunks(a, b)
        s = summarize(changes)
        assert s.modified == 1  # only the paragraph changed

    def test_ignore_whitespace(self):
        a = chunk_markdown("# Title\n\nHello   world")
        b = chunk_markdown("# Title\n\nHello world")
        changes_strict = diff_chunks(a, b, ignore_ws=False)
        changes_ws = diff_chunks(a, b, ignore_ws=True)
        s_strict = summarize(changes_strict)
        s_ws = summarize(changes_ws)
        assert s_ws.modified == 0  # whitespace ignored
        assert s_strict.modified == 1  # whitespace noticed

    def test_heading_level_change(self):
        a = chunk_markdown("## Subheading")
        b = chunk_markdown("### Subheading")
        changes = diff_chunks(a, b)
        s = summarize(changes)
        assert s.modified == 1

    def test_list_reorder(self):
        a = chunk_markdown("- alpha\n- beta\n- gamma")
        b = chunk_markdown("- gamma\n- beta\n- alpha")
        changes = diff_chunks(a, b)
        s = summarize(changes)
        assert s.modified == 1

    def test_code_block_change(self):
        a = chunk_markdown("```\nold code\n```")
        b = chunk_markdown("```\nnew code\n```")
        changes = diff_chunks(a, b)
        s = summarize(changes)
        assert s.modified == 1


# ── Renderer tests ───────────────────────────────────────────────────────────

class TestRenderers:
    def _basic_changes(self):
        a = chunk_markdown("# Title\n\nOld paragraph")
        b = chunk_markdown("# Title\n\nNew paragraph\n\nExtra section")
        return diff_chunks(a, b)

    def test_terminal_output(self):
        out = render_terminal(self._basic_changes())
        assert "added" in out
        assert "modified" in out

    def test_html_output(self):
        out = render_html(self._basic_changes())
        assert "<!DOCTYPE html>" in out
        assert "semdiff" in out

    def test_json_output(self):
        out = render_json(self._basic_changes())
        data = json.loads(out)
        assert "summary" in data
        assert "changes" in data
        assert data["summary"]["added"] >= 1

    def test_json_structure(self):
        out = render_json(self._basic_changes())
        data = json.loads(out)
        for change in data["changes"]:
            assert "type" in change
            assert change["type"] in ("added", "removed", "modified")


# ── CLI integration tests ────────────────────────────────────────────────────

class TestCLI:
    def test_basic_run(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("# Hello\n\nWorld")
        b.write_text("# Hello\n\nEarth")
        rc = main([str(a), str(b)])
        assert rc == 0

    def test_stats_only(self, tmp_path, capsys):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("# Title\n\nOld")
        b.write_text("# Title\n\nNew\n\nAdded")
        rc = main([str(a), str(b), "--stats-only"])
        assert rc == 0
        captured = capsys.readouterr().out
        assert "added" in captured
        assert "modified" in captured

    def test_json_flag(self, tmp_path, capsys):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("Hello")
        b.write_text("Goodbye")
        rc = main([str(a), str(b), "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "changes" in data

    def test_html_flag(self, tmp_path, capsys):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("Hello")
        b.write_text("Goodbye")
        rc = main([str(a), str(b), "--html"])
        assert rc == 0
        assert "<!DOCTYPE html>" in capsys.readouterr().out

    def test_ignore_whitespace_flag(self, tmp_path, capsys):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("Hello   world")
        b.write_text("Hello world")
        rc = main([str(a), str(b), "--stats-only", "--ignore-whitespace"])
        assert rc == 0
        captured = capsys.readouterr().out
        assert "+0 added" in captured
        assert "~0 modified" in captured

    def test_missing_file(self, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("Hello")
        rc = main([str(a), "/nonexistent/file.md"])
        assert rc == 1

    def test_identical_files(self, tmp_path, capsys):
        a = tmp_path / "a.md"
        a.write_text("# Same\n\nContent here")
        rc = main([str(a), str(a), "--stats-only"])
        assert rc == 0
        captured = capsys.readouterr().out
        assert "+0 added" in captured and "-0 removed" in captured and "~0 modified" in captured
