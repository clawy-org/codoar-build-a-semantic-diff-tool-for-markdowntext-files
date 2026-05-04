# semdiff — Semantic Diff for Markdown & Text

A CLI tool that diffs two text or markdown files **semantically** — by sections, paragraphs, and structure — not just line-by-line.

## Quick Start

```bash
python semdiff.py file_a.md file_b.md
```

## Features

- **Smart chunking**: splits by markdown headings, paragraphs, code blocks, and lists
- **Color terminal output**: added (green), removed (red), modified (yellow) with inline sub-diffs
- **Multiple output formats**: terminal (default), `--html`, `--json`
- **Whitespace normalization**: `--ignore-whitespace` flag
- **Summary mode**: `--stats-only` for quick overview
- **Stdlib only**: no external dependencies (uses `difflib`, `ast`, `curses`-free)
- **Python 3.9+** compatible

## Usage

### Default (colored terminal diff)

```
$ python semdiff.py old.md new.md
+3 added, -1 removed, ~2 modified sections

- [heading]
-  ## Old Section

~ [paragraph] (78% similar)
-The quick brown fox jumps.
+The quick brown cat jumps.

+ [paragraph]
+  This is a brand new section.
```

### HTML export

```bash
python semdiff.py old.md new.md --html > diff.html
```

Produces a self-contained HTML file with a dark theme, syntax-highlighted diff. No external CSS or JS needed — just open in a browser.

### JSON output

```bash
python semdiff.py old.md new.md --json
```

Returns a machine-readable JSON object:

```json
{
  "summary": {"added": 3, "removed": 1, "modified": 2},
  "changes": [
    {"type": "modified", "old": {...}, "new": {...}, "similarity": 0.78},
    {"type": "added", "new": {"kind": "paragraph", "text": "..."}},
    ...
  ]
}
```

### Stats only

```bash
$ python semdiff.py old.md new.md --stats-only
+3 added, -1 removed, ~2 modified sections
```

### Ignore whitespace

```bash
python semdiff.py old.md new.md --ignore-whitespace
```

Normalizes spaces and blank lines before comparing, so reformatting doesn't show as changes.

## How It Works

1. **Chunk**: Each file is split into semantic chunks (headings, paragraphs, code blocks, lists) based on markdown structure
2. **Align**: Chunks are aligned using `difflib.SequenceMatcher` for optimal matching
3. **Diff**: Matched chunks are compared; modified ones get an inline line-level sub-diff
4. **Render**: Output in your chosen format with color coding and similarity scores

## Running Tests

```bash
python -m pytest test_semdiff.py -v
```

## Flags Reference

| Flag | Description |
|------|-------------|
| `--html` | Output self-contained HTML diff |
| `--json` | Output machine-readable JSON |
| `--ignore-whitespace` | Normalize whitespace before comparing |
| `--stats-only` | Print summary line only, no diff body |

## Requirements

- Python 3.9+
- No external dependencies (stdlib only)
