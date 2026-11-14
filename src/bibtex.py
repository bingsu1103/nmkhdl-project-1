"""Member 3 — M2 BibTeX adapter.

Collect the bibliography on each version's compilation path (.bib files named by
\\bibliography/\\addbibresource and inline \\bibitem), convert \\bibitem to BibTeX
fields with deterministic regex rules, then deduplicate entries across versions of
one publication and write ``parsed/bibtex.jsonl`` for ``build-parsing-tables``.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .latex_parser import strip_latex_comments

TABLE_FIELDS = ("arxiv_id", "citation_key", "entry_type", "title", "authors", "year", "doi", "journal", "url")
PARSED_STATUSES = {"success", "partial"}

_BIB_CMD_RE = re.compile(r"\\(?:bibliography|addbibresource|nobibliography)\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
_THEBIB_RE = re.compile(r"\\begin\s*\{thebibliography\}(?:\s*\{[^{}]*\})?(.*?)(?:\\end\s*\{thebibliography\}|\Z)", re.S)
_BIBITEM_RE = re.compile(r"\\bibitem\s*(?:\[(?:[^\[\]]|\[[^\]]*\])*\])?\s*\{([^{}]+)\}")
_ENTRY_START_RE = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
_FIELD_NAME_RE = re.compile(r"\s*,?\s*([A-Za-z][\w\-:.]*)\s*=\s*")
_BARE_VALUE_RE = re.compile(r"[^,#\s{}\"]+")
_CONCAT_RE = re.compile(r"\s*#\s*")
_YEAR_RE = re.compile(r"(?<![\d./])((?:18|19|20)\d\d)(?!\d|\.\d)")
_MAX_YEAR = date.today().year + 1  # page numbers like 2062 look like years


def _find_year(text: str, last: bool = False) -> Optional[int]:
    years = [int(m.group(1)) for m in _YEAR_RE.finditer(text) if int(m.group(1)) <= _MAX_YEAR]
    return (years[-1] if last else years[0]) if years else None
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s{}\"',;]+")
_URL_RE = re.compile(r"\\(?:url|href)\s*\{([^{}]+)\}|(https?://[^\s{}]+)")
_ARXIV_RE = re.compile(r"arXiv\s*:?\s*(\d{4}\.\d{4,5})", re.I)
_INITIALS_RE = re.compile(r"^(?:[A-Z][a-z]?\.?\s*-?\s*)+$")

_ACCENTS = {'"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303", "=": "\u0304",
            ".": "\u0307", "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "k": "\u0328"}
_SYMBOLS = {"ss": "ß", "o": "ø", "O": "Ø", "ae": "æ", "AE": "Æ", "oe": "œ", "l": "ł", "L": "Ł", "i": "ı", "aa": "å", "AA": "Å"}


# ---------------------------------------------------------------- LaTeX cleanup

def clean_latex(text: Optional[str]) -> str:
    """Turn a LaTeX field value into plain Unicode text (accents kept, formatting dropped)."""
    if not text:
        return ""
    s = re.sub(r"\\([\"'`^~=.])\s*\{?\s*\\?([A-Za-z])\s*\}?", lambda m: m.group(2) + _ACCENTS[m.group(1)], text)
    s = re.sub(r"\\([cvuHk])\s*\{\s*([A-Za-z])\s*\}", lambda m: m.group(2) + _ACCENTS[m.group(1)], s)
    s = re.sub(r"\\(ss|o|O|ae|AE|oe|l|L|i|aa|AA)(?![A-Za-z])\s*", lambda m: _SYMBOLS[m.group(1)], s)
    s = re.sub(r"\\([&%$#_{}])", r"\1", s)
    s = s.replace("``", '"').replace("''", '"').replace("---", "—").replace("--", "–").replace("~", " ")
    s = re.sub(r"\\[A-Za-z]+\*?", " ", s)  # command names go, their {arguments} stay
    s = s.replace("{", "").replace("}", "").replace("$", "")
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()
    return re.sub(r"\s+([,.;:])", r"\1", s)


def _find_close(text: str, i: int) -> Optional[int]:
    """Index of the bracket closing ``text[i]`` ('{' or '('), counting nested braces."""
    closer = "}" if text[i] == "{" else ")"
    depth = 0
    for j in range(i + 1, len(text)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            if depth == 0 and closer == "}":
                return j
            depth -= 1
        elif c == ")" and closer == ")" and depth == 0:
            return j
    return None


# ---------------------------------------------------------------- .bib parsing

def parse_bib_file(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse BibTeX source into ``[{citation_key, entry_type, fields}]`` plus warnings."""
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    macros: dict[str, str] = {}
    pos = 0
    while True:
        m = _ENTRY_START_RE.search(text, pos)
        if not m:
            break
        entry_type = m.group(1).lower()
        end = _find_close(text, m.end() - 1)
        if end is None:
            warnings.append(f"unclosed_entry:{text[m.start():m.start() + 40]!r}")
            break
        pos = end + 1
        if entry_type == "string":
            macros.update(_parse_fields(text[m.end():end], macros))
            continue
        if entry_type in {"comment", "preamble"}:
            continue
        key, _, body = text[m.end():end].partition(",")
        key = key.strip()
        if not key:
            warnings.append(f"missing_key:@{entry_type}")
            continue
        entries.append({"citation_key": key, "entry_type": entry_type, "fields": _parse_fields(body, macros)})
    return entries, warnings


def _parse_fields(body: str, macros: Optional[dict[str, str]] = None) -> dict[str, str]:
    fields: dict[str, str] = {}
    i, n = 0, len(body)
    while True:
        m = _FIELD_NAME_RE.match(body, i)
        if not m:
            break
        name, i, parts = m.group(1).lower(), m.end(), []
        while i < n:
            if body[i] == "{":
                j = _find_close(body, i)
                j = n if j is None else j
                parts.append(body[i + 1:j])
            elif body[i] == '"':
                j, depth = i + 1, 0
                while j < n and (body[j] != '"' or depth > 0):  # {\"u} inside quotes is not the end
                    depth += {"{": 1, "}": -1}.get(body[j], 0)
                    j += 1
                parts.append(body[i + 1:j])
            else:
                bare = _BARE_VALUE_RE.match(body, i)
                if not bare:
                    break
                parts.append((macros or {}).get(bare.group(0).lower(), bare.group(0)))
                j = bare.end() - 1
            i = j + 1
            concat = _CONCAT_RE.match(body, i)
            if not concat:
                break
            i = concat.end()
        fields[name] = "".join(parts)
    return fields


def _bib_authors(value: str) -> list[str]:
    authors = []
    for name in re.split(r"\s+and\s+", value.strip()):
        name = clean_latex(name)
        if "," in name:  # "Last, First" -> "First Last"
            last, _, first = name.partition(",")
            name = f"{first.strip()} {last.strip()}".strip()
        if name and name.lower() not in {"others", "et al."}:
            authors.append(name)
    return authors


def entry_from_bib(raw: dict[str, Any]) -> dict[str, Any]:
    f = raw["fields"]
    year = _find_year(f.get("year", "") or f.get("date", ""))
    doi = _DOI_RE.search(f.get("doi", ""))
    arxiv = _ARXIV_RE.search(f"arXiv:{f['eprint']}" if f.get("eprint") else f.get("journal", ""))
    url = clean_latex(f.get("url")) or (f"https://arxiv.org/abs/{arxiv.group(1)}" if arxiv else None)
    title, warnings = clean_latex(f.get("title")), []
    if not title:  # validator needs a title; keep the other field values as evidence, like \bibitem
        title = ", ".join(v for v in (clean_latex(x) for x in f.values()) if v) or raw["citation_key"]
        warnings.append("title_from_raw")
    return {
        "citation_key": raw["citation_key"],
        "entry_type": raw["entry_type"],
        "title": title,
        "warnings": warnings,
        "authors": _bib_authors(f.get("author", "")),
        "year": year,
        "doi": doi.group(0).rstrip(".") if doi else None,
        # schema has no booktitle column, so the venue of a conference paper goes to journal
        "journal": clean_latex(f.get("journal") or f.get("booktitle")) or None,
        "url": url,
    }


# ---------------------------------------------------------------- \bibitem conversion

def parse_bibitems(block: str) -> list[tuple[str, str]]:
    """Split a thebibliography body into ``(citation_key, raw_text)`` pairs."""
    matches = list(_BIBITEM_RE.finditer(block))
    items = []
    for k, m in enumerate(matches):
        end = matches[k + 1].start() if k + 1 < len(matches) else len(block)
        items.append((m.group(1).strip(), block[m.end():end].strip()))
    return items


def _split_authors(text: str) -> list[str]:
    text = re.sub(r"\bet\s*al\.?", "", text)
    parts = [p.strip(" .") for p in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", text) if p.strip(" .")]
    merged: list[str] = []
    for p in parts:  # "Vaswani, A., Shazeer, N." -> pair surname with its initials
        if merged and _INITIALS_RE.match(p + ".") and " " not in merged[-1]:
            merged[-1] = f"{p}. {merged[-1]}".replace("..", ".")
        else:
            merged.append(p)
    return [a for a in merged if any(ch.isalpha() for ch in a)]


def _split_sentences(text: str) -> list[str]:
    """Split on '. ' but keep author initials ("A. Vaswani") inside the author sentence."""
    initial_first = bool(re.match(r"[A-Z]\.", text))  # "A. Vaswani" style vs "Vaswani, A." style
    merged: list[str] = []
    for part in (p.strip() for p in re.split(r"(?<=[\w)\]])\.\s+", text)):
        ends_initial = re.search(r"(?:^|[\s.\-])[A-Z]$", merged[-1]) if merged else None
        if ends_initial and (initial_first or not re.search(r",\s*[A-Z]$", merged[-1])):
            merged[-1] += ". " + part
        elif part:
            merged.append(part)
    return merged


def _guess_type(venue: str) -> str:
    v = venue.lower()
    if re.search(r"\bthesis\b", v):
        return "phdthesis"
    if re.match(r"\s*in\b", v) or re.search(r"\b(proc\.?|proceedings|conference|workshop|symposium)\b", v):
        return "inproceedings"
    if re.search(r"arxiv|preprint", v):
        return "misc"
    if re.search(r"journal|trans\.|transactions|letters|review|\d+\s*\(\d+\)|\bvol\.\s*\d", v):  # IEEE: "vol. 60"
        return "article"
    return "misc"


def convert_bibitem(key: str, raw: str) -> tuple[dict[str, Any], list[str]]:
    """Map one \\bibitem to BibTeX fields; a field is set only when the text supports it."""
    warnings: list[str] = []
    doi = _DOI_RE.search(raw)
    url_m = _URL_RE.search(raw)
    url = (url_m.group(1) or url_m.group(2)) if url_m else None
    arxiv = _ARXIV_RE.search(raw)
    if not url and arxiv:
        url = f"https://arxiv.org/abs/{arxiv.group(1)}"
    body = _URL_RE.sub(" ", _DOI_RE.sub(" ", raw))

    quoted = re.search(r"``(.+?)(?:''|\")|\"(.+?)\"", body, re.S)  # IEEE often closes ``Title," with "
    if "\\newblock" in body:  # plain/natbib .bbl layout: authors \newblock title \newblock venue
        blocks = [clean_latex(b).strip(" .,") for b in body.split("\\newblock")]
        authors_txt, title, venue = blocks[0], blocks[1] if len(blocks) > 1 else "", " ".join(blocks[2:])
    elif quoted:
        title = clean_latex(quoted.group(1) or quoted.group(2)).strip(" .,")
        authors_txt, venue = clean_latex(body[:quoted.start()]), clean_latex(body[quoted.end():])
    else:
        sentences = _split_sentences(clean_latex(body))
        authors_txt = sentences[0] if len(sentences) > 1 else ""
        title = sentences[1].strip(" .") if len(sentences) > 1 else ""
        venue = " ".join(sentences[2:])
        warnings.append("no_block_markers")

    year = _find_year(clean_latex(body), last=True)  # the year usually closes the item, after volume/pages
    authors_txt = _YEAR_RE.sub("", re.sub(r"\(\s*\)", "", authors_txt.replace(f"({year})" if year else "\0", "")))
    entry_type = _guess_type(venue)
    venue = re.sub(r"\bdoi\s*:?\s*$", "", re.sub(r"^\s*in\s+", "", venue, flags=re.I), flags=re.I)
    if not title:
        title = clean_latex(raw) or key  # validator needs a title; full text keeps the evidence for matching
        warnings.append("title_from_raw")
    return {
        "citation_key": key,
        "entry_type": entry_type,
        "title": title,
        "authors": _split_authors(authors_txt),
        "year": year,
        "doi": doi.group(0).rstrip(".") if doi else None,
        "journal": venue.strip(" .,") or None if entry_type in {"article", "inproceedings"} else None,
        "url": url,
    }, warnings


# ---------------------------------------------------------------- compilation path

def collect_version_entries(source_dir: str | Path, reachable_files: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Raw bibliography entries of one version, read only from files on its compilation path."""
    root = Path(source_dir)
    entries: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    seen_bib: set[Path] = set()
    for rel in reachable_files:
        tex_path = root / rel
        text = strip_latex_comments(tex_path.read_text(encoding="utf-8", errors="replace"))
        for cmd in _BIB_CMD_RE.finditer(text):
            for name in (n.strip() for n in cmd.group(1).split(",")):
                if not name:
                    continue
                name = name if name.endswith(".bib") else name + ".bib"
                bib = next((p for p in (root / name, tex_path.parent / name) if p.is_file()), None)
                if bib is None:
                    diagnostics.append(f"missing_bib:{name}")
                    continue
                if bib.resolve() in seen_bib:
                    continue
                seen_bib.add(bib.resolve())
                raws, warns = parse_bib_file(bib.read_text(encoding="utf-8", errors="replace"))
                diagnostics += [f"{bib.relative_to(root).as_posix()}:{w}" for w in warns]
                for raw in raws:
                    entries.append({**entry_from_bib(raw), "origin": "bib", "source_file": bib.relative_to(root).as_posix()})
        for block in _THEBIB_RE.finditer(text):
            for key, raw in parse_bibitems(block.group(1)):
                try:
                    entry, warns = convert_bibitem(key, raw)
                except Exception as exc:  # one malformed item must not drop the others
                    diagnostics.append(f"bibitem_error:{key}:{type(exc).__name__}")
                    continue
                entries.append({**entry, "origin": "bibitem", "source_file": rel, "raw": raw, "warnings": warns})
    # Some sources reuse one key for many items (template leftovers); keep them apart so dedup does not merge them.
    counts: dict[str, int] = {}
    for e in entries:
        n = counts[e["citation_key"]] = counts.get(e["citation_key"], 0) + 1
        if n > 1:
            e["citation_key"] = f"{e['citation_key']}__{n}"
            e["warnings"] = [*e["warnings"], "duplicate_key_in_version"]
    return entries, diagnostics


# ---------------------------------------------------------------- dedup across versions

def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower())


def deduplicate_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge entries of ONE publication referring to the same work.

    Same citation key, same DOI, or same normalized title (>= 20 chars, years not
    contradicting) means same reference. The key used in the latest version wins;
    fields are unioned with latest-version priority and conflicts are recorded.
    Returns (unified rows, alias rows, conflict rows).
    """
    parent = list(range(len(entries)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def same_year(a: dict, b: dict) -> bool:
        return a["year"] is None or b["year"] is None or a["year"] == b["year"]

    first_by: dict[tuple, int] = {}
    for i, e in enumerate(entries):
        keys = [("key", e["citation_key"])]
        if e["doi"]:
            keys.append(("doi", e["doi"].lower()))
        t = _norm_title(e["title"])
        if len(t) >= 20 and "title_from_raw" not in e.get("warnings", []):
            keys.append(("title", t))
        for k in keys:
            j = first_by.setdefault(k, i)
            if j != i and (k[0] != "title" or same_year(entries[i], entries[j])):
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for i in range(len(entries)):
        groups.setdefault(find(i), []).append(i)

    rows, aliases, conflicts = [], [], []
    for members in groups.values():
        # latest version first; inside a version keep file order
        ordered = sorted((entries[i] for i in members), key=lambda e: (-e["version"], e["order"]))
        canonical = ordered[0]["citation_key"]
        row: dict[str, Any] = {"arxiv_id": ordered[0]["arxiv_id"], "citation_key": canonical}
        for field in ("entry_type", "title", "authors", "year", "doi", "journal", "url"):
            values = [e[field] for e in ordered if e[field] not in (None, "", [])]
            if field == "title":  # a real title beats raw-text fallback
                values = [e[field] for e in ordered if e[field] and "title_from_raw" not in e.get("warnings", [])] or values
            if field == "entry_type":  # misc is the "unknown" default
                values = [v for v in values if v != "misc"] or values
            row[field] = values[0] if values else ([] if field == "authors" else None)
            distinct = {json.dumps(v, ensure_ascii=False).lower() for v in values}
            if len(distinct) > 1 and field != "entry_type":
                conflicts.append({"arxiv_id": row["arxiv_id"], "citation_key": canonical, "field": field, "chosen": row[field], "dropped": values[1:]})
        rows.append(row)
        for alias in sorted({e["citation_key"] for e in ordered} - {canonical}):
            aliases.append({"arxiv_id": row["arxiv_id"], "alias_key": alias, "canonical_key": canonical})
    rows.sort(key=lambda r: r["citation_key"])
    return rows, aliases, conflicts


# ---------------------------------------------------------------- \cite rewrite

_CITE_RE = re.compile(r"\\((?:no)?cite[A-Za-z]*\*?)\s*((?:\[[^\]]*\]\s*){0,2})\{([^{}]*)\}")


def cited_keys(text: str) -> list[str]:
    """Citation keys used by \\cite-family commands, in order of appearance."""
    return [k.strip() for m in _CITE_RE.finditer(text) for k in m.group(3).split(",") if k.strip() and k.strip() != "*"]


def rewrite_citations(text: str, alias_map: dict[str, str]) -> str:
    """Rename dropped keys to their canonical key inside every \\cite{...}; a repeated key is kept once."""
    def repl(m: re.Match) -> str:
        keys = [alias_map.get(k.strip(), k.strip()) for k in m.group(3).split(",") if k.strip()]
        return f"\\{m.group(1)}{m.group(2)}{{{','.join(dict.fromkeys(keys))}}}"
    return _CITE_RE.sub(repl, text)


def _citation_rows(arxiv_id: str, version: int, keys: list[str], canonical: set[str], alias_map: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for key in dict.fromkeys(keys):
        target = alias_map.get(key, key)
        status = "unresolved" if target not in canonical else ("renamed" if target != key else "ok")
        rows.append({"arxiv_id": arxiv_id, "version": version, "cited_key": key,
                     "canonical_key": target if status != "unresolved" else None, "status": status})
    return rows


# ---------------------------------------------------------------- stage runner

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def run_bibtex_stage(*, data_dir: str | Path) -> dict[str, Any]:
    """Read M2 parser outputs, write parsed/bibtex*.jsonl and a summary with dedup metrics."""
    root = Path(data_dir)
    inputs = {r["versioned_arxiv_id"]: r for r in _read_jsonl(root / "manifests" / "parsing" / "m2_inputs.jsonl")}
    statuses = _read_jsonl(root / "parsed" / "parse_status.jsonl")

    by_paper: dict[str, list[dict[str, Any]]] = {}
    raw_rows: list[dict[str, Any]] = []
    version_rows: list[dict[str, Any]] = []
    cites: dict[tuple[str, int], list[str]] = {}
    for st in statuses:
        arxiv_id, version = st["arxiv_id"], int(st["version"])
        by_paper.setdefault(arxiv_id, [])
        source_dir = inputs.get(st["versioned_arxiv_id"], {}).get("source_dir")
        if st["status"] not in PARSED_STATUSES or not source_dir:
            version_rows.append({"arxiv_id": arxiv_id, "version": version, "status": "skipped", "parse_status": st["status"], "raw_entries": 0, "diagnostics": []})
            continue
        reachable = st.get("reachable_files") or []
        entries, diagnostics = collect_version_entries(root / source_dir, reachable)
        cites[(arxiv_id, version)] = [k for rel in reachable for k in cited_keys(
            strip_latex_comments((root / source_dir / rel).read_text(encoding="utf-8", errors="replace")))]
        for order, e in enumerate(entries):
            e.update(arxiv_id=arxiv_id, version=version, order=order)
        by_paper[arxiv_id] += entries
        raw_rows += entries
        version_rows.append({"arxiv_id": arxiv_id, "version": version, "status": "ok" if entries else "empty", "parse_status": st["status"], "raw_entries": len(entries), "diagnostics": diagnostics})

    unified, aliases, conflicts = [], [], []
    for arxiv_id in sorted(by_paper):
        rows, al, co = deduplicate_entries(by_paper[arxiv_id])
        unified += rows
        aliases += al
        conflicts += co

    canonical_by_paper: dict[str, set[str]] = {}
    for r in unified:
        canonical_by_paper.setdefault(r["arxiv_id"], set()).add(r["citation_key"])
    alias_by_paper: dict[str, dict[str, str]] = {}
    for a in aliases:
        alias_by_paper.setdefault(a["arxiv_id"], {})[a["alias_key"]] = a["canonical_key"]
    citation_rows = [row for (aid, ver), keys in sorted(cites.items()) for row in
                     _citation_rows(aid, ver, keys, canonical_by_paper.get(aid, set()), alias_by_paper.get(aid, {}))]

    out = root / "parsed"
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl_atomic(out / "bibtex.jsonl", [{k: r[k] for k in TABLE_FIELDS} for r in unified])
    _write_jsonl_atomic(out / "bibtex_raw.jsonl", raw_rows)
    _write_jsonl_atomic(out / "bibtex_aliases.jsonl", aliases)
    _write_jsonl_atomic(out / "bibtex_conflicts.jsonl", conflicts)
    _write_jsonl_atomic(out / "bibtex_status.jsonl", version_rows)
    _write_jsonl_atomic(out / "bibtex_citations.jsonl", citation_rows)

    summary = {
        "versions_total": len(version_rows),
        "versions_with_entries": sum(v["status"] == "ok" for v in version_rows),
        "versions_empty": sum(v["status"] == "empty" for v in version_rows),
        "versions_skipped": sum(v["status"] == "skipped" for v in version_rows),
        "raw_entries": len(raw_rows),
        "raw_from_bib": sum(e["origin"] == "bib" for e in raw_rows),
        "raw_from_bibitem": sum(e["origin"] == "bibitem" for e in raw_rows),
        "unified_entries": len(unified),
        "merged_away": len(raw_rows) - len(unified),
        "renamed_keys": len(aliases),
        "field_conflicts": len(conflicts),
        "title_from_raw": sum("title_from_raw" in e["warnings"] for e in raw_rows),
        "missing_bib_files": sum(d.startswith("missing_bib:") for v in version_rows for d in v["diagnostics"]),
        "citations_total": len(citation_rows),
        "citations_renamed": sum(c["status"] == "renamed" for c in citation_rows),
        "citations_unresolved": sum(c["status"] == "unresolved" for c in citation_rows),
    }
    (out / "bibtex_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build parsed/bibtex.jsonl from M2 parser outputs.")
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_bibtex_stage(data_dir=args.data_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
