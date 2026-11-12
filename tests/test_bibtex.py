import json

import pytest

from src.bibtex import (
    cited_keys,
    clean_latex,
    collect_version_entries,
    convert_bibitem,
    deduplicate_entries,
    entry_from_bib,
    parse_bib_file,
    parse_bibitems,
    rewrite_citations,
    run_bibtex_stage,
)
from src.storage import BIBTEX_SCHEMA, create_table_from_records
from src.validate import validate_bibtex_table


# ---------------------------------------------------------------- .bib parsing

def test_parse_bib_braces_quotes_concat_and_macros():
    text = r"""
    @comment{ignored @article{fake, title={no}} }
    @string{nips = "NeurIPS"}
    @inproceedings{vaswani2017,
      title = {Attention is {All} you Need},
      author = "Vaswani, Ashish and Shazeer, Noam and others",
      booktitle = nips # " 2017",
      year = 2017,
      doi = {10.5555/3295222.3295349}
    }
    @article(muller, title="M{\"u}ller's Study", author={M\"{u}ller, J{\"o}rg}, journal={J. Foo}, year={2020})
    """
    raws, warnings = parse_bib_file(text)
    assert warnings == []
    assert [r["citation_key"] for r in raws] == ["vaswani2017", "muller"]
    vas, mul = (entry_from_bib(r) for r in raws)
    assert vas == {
        "citation_key": "vaswani2017", "entry_type": "inproceedings",
        "title": "Attention is All you Need", "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "year": 2017, "doi": "10.5555/3295222.3295349", "journal": "NeurIPS 2017", "url": None,
    }
    assert mul["title"] == "Müller's Study"
    assert mul["authors"] == ["Jörg Müller"]


def test_parse_bib_unclosed_entry_keeps_previous_entries():
    raws, warnings = parse_bib_file("@misc{a, title={A}}\n@misc{b, title={broken")
    assert [r["citation_key"] for r in raws] == ["a"]
    assert warnings and warnings[0].startswith("unclosed_entry")


def test_bib_eprint_becomes_arxiv_url():
    raws, _ = parse_bib_file("@misc{x, title={T}, eprint={1810.04805}, archivePrefix={arXiv}}")
    assert entry_from_bib(raws[0])["url"] == "https://arxiv.org/abs/1810.04805"


def test_clean_latex_accents_and_formatting():
    assert clean_latex(r"\emph{Deep} {L}earning --- Gr\"{o}{\ss}e \& Co.~\cite{x}") == "Deep Learning — Größe & Co. x"
    assert clean_latex(None) == ""


# ---------------------------------------------------------------- \bibitem conversion

@pytest.mark.parametrize("raw, expected", [
    (r"""A.~Vaswani, N.~Shazeer, and J.~Smith.
\newblock Attention is all you need.
\newblock In \emph{Advances in NeurIPS}, pages 5998--6008, 2017.""",
     dict(entry_type="inproceedings", title="Attention is all you need",
          authors=["A. Vaswani", "N. Shazeer", "J. Smith"], year=2017)),
    (r"K. He and J. Sun, ``Deep residual learning,'' in \textit{Proc. CVPR}, 2016. doi:10.1109/CVPR.2016.90",
     dict(entry_type="inproceedings", title="Deep residual learning", authors=["K. He", "J. Sun"],
          year=2016, doi="10.1109/CVPR.2016.90", journal="Proc. CVPR, 2016")),
    (r"Devlin, J., Chang, M., Lee, K. BERT: Pre-training of transformers. arXiv:1810.04805, 2018.",
     dict(entry_type="misc", title="BERT: Pre-training of transformers",
          authors=["J. Devlin", "M. Chang", "K. Lee"], year=2018, url="https://arxiv.org/abs/1810.04805")),
    (r"Smith, J. A study of {\"U}bung. Journal of Research in Learning, 12(3):1--10, 2019.",
     dict(entry_type="article", title="A study of Übung", authors=["J. Smith"], year=2019)),
])
def test_convert_bibitem_styles(raw, expected):
    entry, _ = convert_bibitem("k", raw)
    for field, value in expected.items():
        assert entry[field] == value, field


def test_bibitem_without_structure_keeps_raw_text_as_title():
    entry, warnings = convert_bibitem("w", r"{\em Some notes}")
    assert entry["title"] == "Some notes"
    assert entry["authors"] == [] and entry["year"] is None
    assert "title_from_raw" in warnings


def test_parse_bibitems_optional_labels_and_multiline():
    block = r"""{99}
\bibitem[{Vaswani et~al.(2017)}]{vas}
  A. Vaswani.
  \newblock Attention.
\bibitem[Ho]{ho} J. Ho. Diffusion. 2020.
"""
    items = parse_bibitems(block)
    assert [k for k, _ in items] == ["vas", "ho"]
    assert "Attention" in items[0][1] and "Diffusion" in items[1][1]


# ---------------------------------------------------------------- compilation path

def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_reads_only_bibliography_on_compilation_path(tmp_path):
    _write(tmp_path / "main.tex", "\\documentclass{article}\n% \\bibliography{commented}\n\\input{sec/refs}\n")
    _write(tmp_path / "sec" / "refs.tex", "\\bibliography{a,b.bib,missing}\n"
           "\\begin{thebibliography}{9}\\bibitem{inl} A. B. Inline title. 2001.\\end{thebibliography}")
    _write(tmp_path / "a.bib", "@article{ka, title={From A}, year={2000}}")
    _write(tmp_path / "b.bib", "@misc{kb, title={From B}}")
    _write(tmp_path / "commented.bib", "@misc{no1, title={Commented out}}")
    _write(tmp_path / "unused.bib", "@misc{no2, title={Not on path}}")

    entries, diagnostics = collect_version_entries(tmp_path, ["main.tex", "sec/refs.tex"])

    assert [e["citation_key"] for e in entries] == ["ka", "kb", "inl"]
    assert [e["origin"] for e in entries] == ["bib", "bib", "bibitem"]
    assert entries[0]["source_file"] == "a.bib" and entries[2]["source_file"] == "sec/refs.tex"
    assert diagnostics == ["missing_bib:missing.bib"]


def test_collect_malformed_bibitem_does_not_drop_others(tmp_path, monkeypatch):
    import src.bibtex as bibtex

    real = bibtex.convert_bibitem

    def flaky(key, raw):
        if key == "bad":
            raise ValueError("boom")
        return real(key, raw)

    monkeypatch.setattr(bibtex, "convert_bibitem", flaky)
    _write(tmp_path / "main.tex", "\\begin{thebibliography}{9}\\bibitem{ok1} A. T. One.\\bibitem{bad} x\\bibitem{ok2} B. T. Two.\\end{thebibliography}")
    entries, diagnostics = collect_version_entries(tmp_path, ["main.tex"])
    assert [e["citation_key"] for e in entries] == ["ok1", "ok2"]
    assert diagnostics == ["bibitem_error:bad:ValueError"]


# ---------------------------------------------------------------- dedup

def _entry(version, key, order=0, **fields):
    base = dict(arxiv_id="2510.19401", version=version, order=order, citation_key=key, entry_type="misc",
                title="", authors=[], year=None, doi=None, journal=None, url=None, warnings=[])
    base.update(fields)
    return base


def test_dedup_statement_worked_example():
    title = "Attention Is All You Need"
    entries = [
        _entry(1, "vaswani2017", title=title, authors=["A. Vaswani"], year=2017),
        _entry(2, "vit_transformer", title=title, authors=["A. Vaswani"], year=2017, doi="10.1000/abc"),
        _entry(3, "vit_transformer", title=title, authors=["A. Vaswani"]),
    ]
    rows, aliases, conflicts = deduplicate_entries(entries)
    assert rows == [{
        "arxiv_id": "2510.19401", "citation_key": "vit_transformer", "entry_type": "misc", "title": title,
        "authors": ["A. Vaswani"], "year": 2017, "doi": "10.1000/abc", "journal": None, "url": None,
    }]
    assert aliases == [{"arxiv_id": "2510.19401", "alias_key": "vaswani2017", "canonical_key": "vit_transformer"}]
    assert conflicts == []


def test_dedup_does_not_merge_different_years_or_short_titles():
    entries = [
        _entry(1, "a", title="A Survey of Deep Learning Methods", year=2015),
        _entry(1, "b", title="A Survey of Deep Learning Methods", year=2021, order=1),
        _entry(1, "c", title="Intro", order=2),
        _entry(1, "d", title="Intro", order=3),
    ]
    rows, aliases, _ = deduplicate_entries(entries)
    assert sorted(r["citation_key"] for r in rows) == ["a", "b", "c", "d"]
    assert aliases == []


def test_dedup_records_field_conflicts_and_prefers_latest_version():
    entries = [
        _entry(1, "k", title="Same Reference Title Here", journal="Old Venue"),
        _entry(2, "k", title="Same Reference Title Here", journal="New Venue"),
    ]
    rows, _, conflicts = deduplicate_entries(entries)
    assert rows[0]["journal"] == "New Venue"
    assert conflicts == [{"arxiv_id": "2510.19401", "citation_key": "k", "field": "journal",
                          "chosen": "New Venue", "dropped": ["Old Venue"]}]


# ---------------------------------------------------------------- \\cite rewrite

def test_rewrite_citations_multi_key_optional_args_and_duplicates():
    aliases = {"vaswani2017": "vit", "old": "new"}
    text = r"See \cite{vaswani2017, b} and \citep[see][p.~2]{old,new}, \citet*{x}, \nocite{*}."
    assert rewrite_citations(text, aliases) == r"See \cite{vit,b} and \citep[see][p.~2]{new}, \citet*{x}, \nocite{*}."
    assert cited_keys(text) == ["vaswani2017", "b", "old", "new", "x"]


# ---------------------------------------------------------------- stage end-to-end

def test_run_bibtex_stage_output_passes_m4_validator(tmp_path):
    def version_dir(v):
        return tmp_path / "corpus" / "tex" / "2510.19401" / f"2510.19401v{v}"

    _write(version_dir(1) / "main.tex", "\\documentclass{article} As in \\cite{vaswani2017,ghost}.\\bibliography{refs}")
    _write(version_dir(1) / "refs.bib", "@article{vaswani2017, title={Attention Is All You Need}, author={Vaswani, Ashish}, year={2017}}")
    _write(version_dir(2) / "main.tex", "\\documentclass{article}\\begin{thebibliography}{1}"
           "\\bibitem{vit_transformer} A.~Vaswani.\n\\newblock Attention is all you need.\n\\newblock arXiv preprint, 2017. doi:10.1000/abc\n"
           "\\end{thebibliography}")
    inputs = [
        {"arxiv_id": "2510.19401", "versioned_arxiv_id": f"2510.19401v{v}", "version": v,
         "source_dir": f"corpus/tex/2510.19401/2510.19401v{v}"} for v in (1, 2)
    ] + [{"arxiv_id": "2510.19401", "versioned_arxiv_id": "2510.19401v3", "version": 3, "source_dir": None}]
    statuses = [
        {"arxiv_id": "2510.19401", "versioned_arxiv_id": f"2510.19401v{v}", "version": v,
         "status": "success", "reachable_files": ["main.tex"]} for v in (1, 2)
    ] + [{"arxiv_id": "2510.19401", "versioned_arxiv_id": "2510.19401v3", "version": 3, "status": "no_tex_bib", "reachable_files": []}]
    _write(tmp_path / "manifests" / "parsing" / "m2_inputs.jsonl", "".join(json.dumps(r) + "\n" for r in inputs))
    _write(tmp_path / "parsed" / "parse_status.jsonl", "".join(json.dumps(r) + "\n" for r in statuses))

    summary = run_bibtex_stage(data_dir=tmp_path)

    assert summary["raw_entries"] == 2 and summary["unified_entries"] == 1
    assert summary["renamed_keys"] == 1 and summary["versions_skipped"] == 1
    rows = [json.loads(line) for line in (tmp_path / "parsed" / "bibtex.jsonl").read_text().splitlines()]
    assert rows[0]["citation_key"] == "vit_transformer" and rows[0]["doi"] == "10.1000/abc" and rows[0]["year"] == 2017
    table = create_table_from_records(rows, BIBTEX_SCHEMA)
    report = validate_bibtex_table(table)
    assert report.is_valid, report.to_dict()
    citations = [json.loads(line) for line in (tmp_path / "parsed" / "bibtex_citations.jsonl").read_text().splitlines()]
    assert [(c["cited_key"], c["canonical_key"], c["status"]) for c in citations] == [
        ("vaswani2017", "vit_transformer", "renamed"), ("ghost", None, "unresolved")]
    assert summary["citations_renamed"] == 1 and summary["citations_unresolved"] == 1
