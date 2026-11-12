from src.bibtex import (
    clean_latex,
    entry_from_bib,
    parse_bib_file,
)


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
