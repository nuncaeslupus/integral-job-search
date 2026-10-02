"""One annotatable section per paragraph for a document that has no headings (T184).

`claude-arsenal/scripts/create_reader.py` derives a reader's annotatable sections
from `##`/`###` headings. A cover letter is about eleven paragraphs and no
headings at all, so the whole letter became **one** section — one comment box for
a document whose entire review is per-sentence corrections. Every
candidate-facing document this repository produces (letters, LinkedIn messages,
profile summaries) is heading-less, so that is a class of document, not one.

The vendored bundle is refreshed by `/init` and is never hand-edited, so the fix
is caller-side: `sectioned(markdown)` rewrites a heading-poor document into one
with a `##` heading per paragraph, and the CLI (`python -m
integral.reader_sections --input letter.md ...`) writes that copy to a scratch
directory and hands it to `create_reader.py` with the same arguments.

**Edge decisions, each from the task text unless said otherwise.**

- *Fewer than two headings means split.* A document with zero or **one** heading
  is split; two or more is returned **unchanged** (the same string, byte for
  byte — specs and plans are right as they are). "Heading" is the generator's own
  `HEADING_RE` (`##` or `###`, outside a ``` fence), mirrored here so the two can
  never disagree about which documents are already sectioned. One `###` under a
  title is one heading, and splits.
- *`#` title.* The first `# ` line outside a fence stays above the sections as
  the document title, exactly as the generator treats it; it is never a section.
- *A lone heading in a split document* is not left as a heading in a body (the
  generator would then cut a stray extra section there). It becomes the label of
  the section made from the paragraph that follows it, and is a section of its
  own, empty, when nothing follows. Its text survives as the label, verbatim:
  never shortened or stripped of markup, so no word of it is lost.
- *Paragraphs* are runs of lines separated by blank lines. A line holding only
  whitespace is blank, runs of blank lines are one separator, and CRLF / CR line
  endings are normalised to `\\n` (this applies to a split document only).
  Blank lines **inside a ``` fence** do not end a paragraph: a code block is one
  piece. An unclosed fence runs to the end of the document.
- *Nothing is lost or reordered.* Each paragraph's lines are copied verbatim
  into its section body, in document order. The only dropped text is a
  paragraph made solely of a horizontal rule (`---`), which the generator
  discards from every body anyway and which is not text a reviewer annotates.
- *Labels.* `N. ` plus the first six words of the paragraph's first line, with
  list markers and markdown punctuation removed and `…` appended when words were
  cut. A paragraph whose first line is nothing but markup is labelled `N.
  paragraph`. The number is on **every** label, so two paragraphs that open with
  the same words stay distinct, in the heading and in the generator's section id
  alike; it also makes the generator read the label as `§N`, which is the order
  a reviewer already refers to ("the third paragraph").
- *Not split:* no `--input` (auto-discovery, workspace mode) is passed through
  untouched, because there is no single file to rewrite.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
CREATE_READER = _REPO_ROOT / "claude-arsenal" / "scripts" / "create_reader.py"

# Mirrors `create_reader.HEADING_RE` / `HR_RE` / the fence test in `parse_doc`.
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*)$")
_TITLE_RE = re.compile(r"^#\s+(.*)$")
_HR_RE = re.compile(r"^-{3,}\s*$")
_LIST_MARKER_RE = re.compile(r"^(?:[-+*]|\d+[.)])\s+")
_MARKUP_RE = re.compile(r"[`*_~#>\[\]()<>|\\]")


def _is_fence(line: str) -> bool:
    return line.strip().startswith("```")


def count_headings(markdown: str) -> int:
    """`##`/`###` headings outside a fence, as `create_reader.parse_doc` sees them."""
    n = 0
    in_code = False
    for line in markdown.split("\n"):
        if _is_fence(line):
            in_code = not in_code
        elif not in_code and _HEADING_RE.match(line):
            n += 1
    return n


def label_for(paragraph_first_line: str) -> str:
    """First few words of a paragraph, stripped of markdown, never empty."""
    text = _LIST_MARKER_RE.sub("", paragraph_first_line.strip())
    words = _MARKUP_RE.sub("", text).split()
    if not words:
        return "paragraph"
    label = " ".join(words[:6])
    return label + "…" if len(words) > 6 else label


def paragraphs(markdown: str) -> tuple[str | None, list[tuple[str | None, str]]]:
    """Split into `(title, [(heading_label_or_None, paragraph_text), ...])`.

    `heading_label` is a lone heading's text that immediately precedes the
    paragraph; `paragraph_text` is `""` for a heading with nothing after it.
    """
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title: str | None = None
    out: list[tuple[str | None, str]] = []
    current: list[str] = []
    pending: str | None = None
    in_code = False

    def flush() -> None:
        nonlocal pending
        if current:
            body = "\n".join(current)
            current.clear()
            if not all(_HR_RE.match(ln) for ln in body.split("\n")):
                out.append((pending, body))
                pending = None

    for line in lines:
        if _is_fence(line):
            in_code = not in_code
            current.append(line)
            continue
        if in_code:
            current.append(line)
            continue
        if not line.strip():
            flush()
            continue
        if title is None and (m := _TITLE_RE.match(line)):
            flush()
            title = m.group(1).strip()
            continue
        if m := _HEADING_RE.match(line):
            flush()
            if pending is not None:
                out.append((pending, ""))
            pending = m.group(2).strip()
            continue
        current.append(line)
    flush()
    if pending is not None:
        out.append((pending, ""))
    return title, out


def sectioned(markdown: str) -> str:
    """Return `markdown` with one `##` section per paragraph when it has under two headings.

    A document with two or more headings is returned as the very same string.
    """
    if count_headings(markdown.replace("\r\n", "\n").replace("\r", "\n")) >= 2:
        return markdown
    title, items = paragraphs(markdown)
    blocks: list[str] = []
    if title is not None:
        blocks.append(f"# {title}")
    for n, (heading, body) in enumerate(items, start=1):
        # A lone heading is the candidate's own text: it becomes the label
        # verbatim, never truncated or stripped, or the reader would show a
        # letter missing words (#621 second reader, F1). Only a label derived
        # from a paragraph's opening is shortened, and that paragraph is shown whole.
        label = heading if heading is not None else label_for(body.split("\n", 1)[0])
        head = f"## {n}. {label}"
        blocks.append(f"{head}\n\n{body}" if body else head)
    return "\n\n".join(blocks) + "\n"


def _input_arg(argv: list[str]) -> tuple[int, str, bool] | None:
    """Index, value and whether it is the `--input=FILE` form, else None."""
    for i, arg in enumerate(argv):
        if arg == "--input" and i + 1 < len(argv):
            return i + 1, argv[i + 1], False
        if arg.startswith("--input="):
            return i, arg.split("=", 1)[1], True
    return None


def _names_output_dir(arg: str) -> bool:
    name = arg.split("=", 1)[0]
    return len(name) > len("--o") and "--output-dir".startswith(name)


def main(argv: list[str] | None = None) -> int:
    """Run `create_reader.py` with the same arguments over a sectioned copy of `--input`."""
    argv = list(sys.argv[1:] if argv is None else argv)
    found = _input_arg(argv)
    cmd = ["uv", "run", "--with", "markdown", "python3", str(CREATE_READER)]
    if found is None:
        return subprocess.run([*cmd, *argv], check=False).returncode
    idx, value, joined = found
    source = Path(value)
    if not source.is_file():
        print(f"✗ {source} not found", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as scratch:
        # Same file name: the generator names its outputs and its section ids
        # from the input stem.
        copy = Path(scratch) / source.name
        copy.write_text(sectioned(source.read_text(encoding="utf-8")), encoding="utf-8")
        new = [*argv]
        new[idx] = f"--input={copy}" if joined else str(copy)
        # argparse accepts any unambiguous prefix (`--out X`), so any prefix of
        # `--output-dir` counts as the caller having chosen one.
        if not any(_names_output_dir(a) for a in argv):
            new += ["--output-dir", str(source.resolve().parent)]
        return subprocess.run([*cmd, *new], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
