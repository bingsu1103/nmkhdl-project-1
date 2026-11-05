"""Compilation-path discovery and first-pass hierarchical LaTeX parser.

This parser intentionally keeps raw semantic LaTeX content. Fine-grained cleanup,
BibTeX normalization and cross-version deduplication are separate downstream stages.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable


class LatexParseError(RuntimeError):
    """Compilation path or hierarchy could not be built safely."""


@dataclass(slots=True)
class Element:
    element_id: str
    kind: str
    content: str
    parent_id: str | None
    source_file: str | None = None
    children: list["Element"] = field(default_factory=list)

    def to_dict(self) -> dict:
        value = asdict(self)
        return value


@dataclass(slots=True)
class CompilationPath:
    status: str
    root_file: str | None
    files: list[str]
    unused_tex_files: list[str]
    diagnostics: list[str]


@dataclass(slots=True)
class ParsedVersion:
    arxiv_id: str
    version: int
    status: str
    root_file: str | None
    elements: list[Element]
    diagnostics: list[str]
    reachable_files: list[str]
    unused_tex_files: list[str]


_SECTION_COMMANDS = [
    "part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph"
]
_SECTION_LEVEL = {name: i for i, name in enumerate(_SECTION_COMMANDS)}
_HEADING_RE = re.compile(
    r"\\(?P<star>\\*)?(?P<cmd>" + "|".join(_SECTION_COMMANDS) + r")\*?\s*(?:\[[^\]]*\]\s*)?\{(?P<title>(?:[^{}]|\\\{|\\\})*)\}",
    re.S,
)
_INCLUDE_RE = re.compile(r"\\(?:input|include)\s*\{(?P<path>[^{}]+)\}")
_DOC_CLASS_RE = re.compile(r"\\documentclass(?:\s*\[[^\]]*\])?\s*\{[^{}]+\}")
_BEGIN_RE = re.compile(r"\\begin\s*\{(?P<env>[^{}]+)\}")
_END_RE = re.compile(r"\\end\s*\{(?P<env>[^{}]+)\}")
_MATH_ENV = {"equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*", "displaymath"}
_LIST_ENV = {"itemize", "enumerate", "description"}
_FIGURE_ENV = {"figure", "figure*", "table", "table*"}


def strip_latex_comments(text: str) -> str:
    """Remove comments and mask verbatim-like environments from parser-visible text."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_verbatim: str | None = None
    for line in lines:
        if in_verbatim:
            out.append("\n" if line.endswith("\n") else "")
            if re.search(r"\\end\{" + re.escape(in_verbatim) + r"\}", line):
                in_verbatim = None
            continue
        begin = re.search(r"\\begin\{(verbatim\*?|lstlisting|minted)\}", line)
        if begin:
            if re.search(r"\\end\{" + re.escape(begin.group(1)) + r"\}", line[begin.end():]):
                out.append("\n" if line.endswith("\n") else "")
            else:
                in_verbatim = begin.group(1)
                out.append("\n" if line.endswith("\n") else "")
            continue
        chars: list[str] = []
        i = 0
        while i < len(line):
            if line[i] == "%":
                backslashes = 0
                j = i - 1
                while j >= 0 and line[j] == "\\":
                    backslashes += 1
                    j -= 1
                if backslashes % 2 == 0:
                    chars.append("\n" if line.endswith("\n") else "")
                    break
            chars.append(line[i])
            i += 1
        out.append("".join(chars))
    return "".join(out)


def find_compilation_path(source_dir: str | Path) -> CompilationPath:
    root = Path(source_dir).resolve()
    tex_files = sorted(p for p in root.rglob("*.tex") if p.is_file())
    candidates: list[Path] = []
    contents: dict[Path, str] = {}
    for path in tex_files:
        try:
            cleaned = strip_latex_comments(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        contents[path] = cleaned
        if _DOC_CLASS_RE.search(cleaned):
            candidates.append(path)
    if not candidates:
        return CompilationPath("no_root", None, [], [p.relative_to(root).as_posix() for p in tex_files], ["No .tex file contains a live \\documentclass declaration."])
    if len(candidates) > 1:
        return CompilationPath(
            "multiple_roots", None, [],
            [p.relative_to(root).as_posix() for p in tex_files],
            ["Multiple .tex files contain \\documentclass: " + ", ".join(p.relative_to(root).as_posix() for p in candidates)],
        )

    root_file = candidates[0]
    visited: list[Path] = []
    visiting: set[Path] = set()
    diagnostics: list[str] = []

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if not _is_relative_to(resolved, root):
            diagnostics.append(f"path_escape:{path}")
            return
        if resolved in visiting:
            diagnostics.append(f"include_cycle:{resolved.relative_to(root).as_posix()}")
            return
        if resolved in visited:
            diagnostics.append(f"repeated_include:{resolved.relative_to(root).as_posix()}")
            return
        if not resolved.is_file():
            diagnostics.append(f"missing_include:{resolved.relative_to(root).as_posix()}")
            return
        visiting.add(resolved)
        visited.append(resolved)
        text = contents.get(resolved)
        if text is None:
            text = strip_latex_comments(resolved.read_text(encoding="utf-8", errors="replace"))
            contents[resolved] = text
        for match in _INCLUDE_RE.finditer(text):
            raw = match.group("path").strip()
            if not raw or "\\" in raw or PurePosixPath(raw).is_absolute():
                diagnostics.append(f"invalid_include:{raw}")
                continue
            target = (resolved.parent / raw)
            if target.suffix == "":
                target = target.with_suffix(".tex")
            elif target.suffix.lower() != ".tex":
                diagnostics.append(f"non_tex_include:{raw}")
                continue
            visit(target)
        visiting.remove(resolved)

    visit(root_file)
    used = [p.relative_to(root).as_posix() for p in visited]
    unused = [p.relative_to(root).as_posix() for p in tex_files if p not in visited]
    return CompilationPath("success" if not any(d.startswith(("missing_include", "path_escape", "include_cycle")) for d in diagnostics) else "partial",
                           root_file.relative_to(root).as_posix(), used, unused, diagnostics)


def parse_latex_version(
    source_dir: str | Path, *, arxiv_id: str, version: int
) -> ParsedVersion:
    path = find_compilation_path(source_dir)
    if path.status == "no_root":
        return ParsedVersion(arxiv_id, version, "no_root", None, [], path.diagnostics, [], path.unused_tex_files)
    if path.status == "multiple_roots":
        return ParsedVersion(arxiv_id, version, "multiple_roots", None, [], path.diagnostics, [], path.unused_tex_files)
    root = Path(source_dir).resolve()
    combined = _expand_compilation_source(root / path.root_file, root, set())
    elements = build_hierarchy(combined, arxiv_id=arxiv_id, version=version, source_file=path.root_file)
    return ParsedVersion(
        arxiv_id, version, "success" if path.status == "success" else "partial",
        path.root_file, elements, path.diagnostics, path.files, path.unused_tex_files,
    )


def _expand_compilation_source(path: Path, root: Path, active: set[Path]) -> str:
    """Inline reachable inputs at their source position, preserving TeX compilation order."""
    resolved = path.resolve()
    if not _is_relative_to(resolved, root.resolve()) or resolved in active or not resolved.is_file():
        return ""
    active.add(resolved)
    source = resolved.read_text(encoding="utf-8", errors="replace")
    output: list[str] = []
    for line in source.splitlines(keepends=True):
        visible = strip_latex_comments(line)
        matches = list(_INCLUDE_RE.finditer(visible))
        if not matches:
            output.append(line)
            continue
        cursor = 0
        for match in matches:
            raw = match.group("path").strip()
            output.append(line[cursor:match.start()])
            if raw and "\\" not in raw and not PurePosixPath(raw).is_absolute():
                child = resolved.parent / raw
                if child.suffix == "":
                    child = child.with_suffix(".tex")
                if child.suffix.lower() == ".tex":
                    output.append(_expand_compilation_source(child, root, active))
            cursor = match.end()
        output.append(line[cursor:])
    active.remove(resolved)
    return "".join(output)


def build_hierarchy(text: str, *, arxiv_id: str, version: int = 1, source_file: str | None = None) -> list[Element]:
    """Build a deterministic tree with document/heading/list and semantic leaves."""
    text = strip_latex_comments(text)
    document_start = re.search(r"\\begin\{document\}", text)
    if document_start:
        text = text[document_start.end():]
    text = re.sub(r"\\end\{document\}", "\n", text)
    text = re.sub(r"\\maketitle\b.*?(?=\\(?:begin\{abstract\}|part|chapter|section)|\Z)", "\n", text, flags=re.S)
    root = Element(f"{arxiv_id}#root{version}", "document", f"{arxiv_id} version {version}", None, source_file)
    nodes = [root]
    heading_stack: list[tuple[int, Element]] = [(-1, root)]
    current_parent = root
    list_stack: list[tuple[Element, Element]] = []
    cursor = 0
    counter = 0
    excluded = False

    def add(kind: str, content: str, parent: Element, src: str | None = source_file) -> Element:
        nonlocal counter
        counter += 1
        node = Element(f"{arxiv_id}#{kind[:1]}{counter}", kind, _normalize_space(content), parent.element_id, src)
        parent.children.append(node)
        nodes.append(node)
        return node

    # Walk heading, environment and \item markers in source order.
    token_re = re.compile(
        r"\\(?P<heading>(?:" + "|".join(_SECTION_COMMANDS) + r")\*?)\s*(?:\[[^\]]*\]\s*)?\{(?P<title>(?:[^{}]|\\\{|\\\})*)\}"
        r"|\\begin\{(?P<begin>[^{}]+)\}|\\end\{(?P<end>[^{}]+)\}|\\item\b"
    )
    for match in token_re.finditer(text):
        if match.start() < cursor:
            continue
        if match.start() > cursor and not excluded:
            _emit_content(text[cursor:match.start()], current_parent, add)
        cursor = match.end()
        if match.group("heading"):
            command = match.group("heading").rstrip("*")
            title = match.group("title").strip()
            low = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", "", title).strip().lower()
            if command in {"section", "chapter"} and low in {"references", "bibliography", "reference"}:
                excluded = True
                continue
            if excluded and command in {"section", "chapter"}:
                excluded = False
            level = _SECTION_LEVEL[command]
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            parent = heading_stack[-1][1] if heading_stack else root
            node = add("heading", title, parent)
            heading_stack.append((level, node))
            current_parent = node
        elif match.group("begin"):
            env = match.group("begin").strip()
            if env in _LIST_ENV:
                previous_parent = current_parent
                node = add("list", env, current_parent)
                list_stack.append((node, previous_parent))
                current_parent = node
            elif env in _MATH_ENV:
                end_match = re.search(r"\\end\{" + re.escape(env) + r"\}", text[match.end():])
                if end_match:
                    body_start = match.end()
                    body_end = body_start + end_match.start()
                    add("block_formula", text[body_start:body_end], current_parent)
                    cursor = body_start + end_match.end()
            elif env in _FIGURE_ENV:
                end_match = re.search(r"\\end\{" + re.escape(env) + r"\}", text[match.end():])
                if end_match:
                    body_start = match.end()
                    body_end = body_start + end_match.start()
                    add("figure", text[body_start:body_end], current_parent)
                    cursor = body_start + end_match.end()
        elif match.group("end"):
            env = match.group("end").strip()
            if env in _LIST_ENV and list_stack:
                _, previous_parent = list_stack.pop()
                current_parent = previous_parent
        elif match.group(0) == r"\item":
            if list_stack:
                current_parent = list_stack[-1][0]
            current_parent = add("list_item", "item", current_parent)

    if cursor < len(text) and not excluded:
        _emit_content(text[cursor:], current_parent, add)
    return nodes


def _emit_content(raw: str, parent: Element, add) -> None:
    raw = re.sub(r"\\(?:label|ref|eqref|cite|citet|citep)\s*\{[^{}]*\}", " ", raw)
    raw = re.sub(r"\\(?:centering|noindent|smallskip|medskip|bigskip|vspace|hspace)\*?(?:\[[^\]]*\]|\{[^{}]*\})?", " ", raw)
    # Display math delimited by \[...\] and $$...$$.
    patterns = [
        re.compile(r"\\\[(.*?)\\\]", re.S),
        re.compile(r"\$\$(.*?)\$\$", re.S),
    ]
    spans: list[tuple[int, int, str, str]] = []
    for pattern in patterns:
        for match in pattern.finditer(raw):
            spans.append((match.start(), match.end(), "block_formula", match.group(1)))
    spans.sort()
    pos = 0
    for start, end, kind, body in spans:
        if start < pos:
            continue
        _emit_prose(raw[pos:start], parent, add)
        add(kind, body, parent)
        pos = end
    _emit_prose(raw[pos:], parent, add)


def _emit_prose(raw: str, parent: Element, add) -> None:
    raw = re.sub(r"(?s)\\begin\{(?:abstract|thebibliography)\}.*?\\end\{(?:abstract|thebibliography)\}", " ", raw)
    raw = re.sub(r"\\(?:[A-Za-z@]+\*?)(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", raw)
    raw = re.sub(r"\\[A-Za-z@]+\*?", " ", raw)
    raw = raw.replace("~", " ")
    raw = re.sub(r"(?m)^\s*[%#].*$", " ", raw)
    for sentence in split_sentences(raw):
        if sentence.strip():
            add("sentence", sentence, parent)


def split_sentences(text: str) -> list[str]:
    """Split prose at sentence punctuation while protecting common LaTeX false stops."""
    value = re.sub(r"\s+", " ", text).strip()
    if not value:
        return []
    protected = value
    placeholders: dict[str, str] = {}
    patterns = [
        r"\$[^$]*\$|\\\(.*?\\\)",
        r"\\\.",
        r"\b(?:i\.e|e\.g|et al|cf|vs|Fig|Figs|Eq|Eqs|Sec|Dr|Prof|No)\.",
        r"https?://[^\s]+",
        r"\b\d+\.\d+\b",
    ]
    counter = 0
    for pattern in patterns:
        for match in list(re.finditer(pattern, protected, flags=re.I))[::-1]:
            token = f"§DOT{counter}§"
            counter += 1
            placeholders[token] = match.group(0).replace(".", "§PERIOD§")
            protected = protected[:match.start()] + token + protected[match.end():]
    chunks = re.split(r"(?<=[.!?])\s+(?=(?:[A-Z0-9\\]))", protected)
    result = []
    for chunk in chunks:
        for token, original in placeholders.items():
            chunk = chunk.replace(token, original)
        chunk = chunk.replace("§PERIOD§", ".").strip()
        if chunk:
            result.append(chunk)
    return result


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
