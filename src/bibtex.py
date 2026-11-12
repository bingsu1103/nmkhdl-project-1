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
    year = _YEAR_RE.search(f.get("year", "") or f.get("date", ""))
    doi = _DOI_RE.search(f.get("doi", ""))
    arxiv = _ARXIV_RE.search(f"arXiv:{f['eprint']}" if f.get("eprint") else f.get("journal", ""))
    url = clean_latex(f.get("url")) or (f"https://arxiv.org/abs/{arxiv.group(1)}" if arxiv else None)
    return {
        "citation_key": raw["citation_key"],
        "entry_type": raw["entry_type"],
        "title": clean_latex(f.get("title")),
        "authors": _bib_authors(f.get("author", "")),
        "year": int(year.group(1)) if year else None,
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
    if re.search(r"journal|trans\.|transactions|letters|review|\d+\s*\(\d+\)", v):
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

    quoted = re.search(r"``(.+?)''|\"(.+?)\"", body, re.S)
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

    year = _YEAR_RE.search(clean_latex(body))
    authors_txt = _YEAR_RE.sub("", re.sub(r"\(\s*\)", "", authors_txt.replace(f"({year.group(1)})" if year else "\0", "")))
    entry_type = _guess_type(venue)
    venue = re.sub(r"\bdoi\s*:?\s*$", "", re.sub(r"^\s*in\s+", "", venue, flags=re.I), flags=re.I)
    if not title:
        title = clean_latex(raw)  # validator needs a title; full text keeps the evidence for matching
        warnings.append("title_from_raw")
    return {
        "citation_key": key,
        "entry_type": entry_type,
        "title": title,
        "authors": _split_authors(authors_txt),
        "year": int(year.group(1)) if year else None,
        "doi": doi.group(0).rstrip(".") if doi else None,
        "journal": venue.strip(" .,") or None if entry_type in {"article", "inproceedings"} else None,
        "url": url,
    }, warnings
