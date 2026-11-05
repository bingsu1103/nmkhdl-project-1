from src.latex_parser import (
    build_hierarchy, find_compilation_path, split_sentences,
)


def test_compilation_path_follows_nested_inputs_and_ignores_comments(tmp_path):
    (tmp_path / "renamed.tex").write_text(
        r"""\documentclass{article}
% \input{not-real}
\begin{document}
\input{sections/intro}
\end{document}
""", encoding="utf-8"
    )
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections/intro.tex").write_text(r"\section{Intro} Hello.", encoding="utf-8")
    (tmp_path / "unused.tex").write_text(r"\section{Not included} Bye.", encoding="utf-8")
    path = find_compilation_path(tmp_path)
    assert path.status == "success"
    assert path.root_file == "renamed.tex"
    assert path.files == ["renamed.tex", "sections/intro.tex"]
    assert path.unused_tex_files == ["unused.tex"]


def test_multiple_roots_are_explicit(tmp_path):
    (tmp_path / "a.tex").write_text(r"\documentclass{article}")
    assert find_compilation_path(tmp_path).status == "success"
    (tmp_path / "b.tex").write_text(r"\documentclass{report}")
    assert find_compilation_path(tmp_path).status == "multiple_roots"


def test_missing_include_is_diagnostic(tmp_path):
    (tmp_path / "main.tex").write_text(r"\documentclass{article}\input{missing}")
    result = find_compilation_path(tmp_path)
    assert result.status == "partial"
    assert any(x.startswith("missing_include") for x in result.diagnostics)


def test_hierarchy_includes_starred_acknowledgements_and_excludes_references():
    source = r"""
    \begin{document}
    \section{Introduction}
    This is the first sentence. This is second.
    \subsection*{Background}
    We use a model.
    \section*{Acknowledgements}
    Thanks to everyone.
    \section{References}
    This reference text must not appear.
    \end{document}
    """
    nodes = build_hierarchy(source, arxiv_id="2509.21047")
    contents = [n.content for n in nodes]
    assert "Acknowledgements" in contents
    assert not any("reference text" in c.lower() for c in contents)
    assert any(n.kind == "sentence" and "first sentence." in n.content for n in nodes)


def test_formula_and_figure_are_leaves():
    source = r"""
    \begin{document}
    \section{Method}
    Prose before.
    \begin{equation}
    x = y + 1
    \end{equation}
    \begin{figure}
    \caption{Example}
    \end{figure}
    \end{document}
    """
    nodes = build_hierarchy(source, arxiv_id="2509.21047")
    assert any(n.kind == "block_formula" and "x = y + 1" in n.content for n in nodes)
    assert any(n.kind == "figure" and "caption" in n.content for n in nodes)


def test_sentence_split_protects_abbreviations_urls_and_decimals():
    result = split_sentences(
        "We use i.e. a baseline by Smith et al. in Fig. 1. Score is 0.95. See https://a.b/c."
    )
    assert len(result) == 3
    assert "i.e." in result[0]
    assert "et al." in result[0]
    assert "0.95" in result[1]
    assert "https://a.b/c" in result[2]


def test_itemize_items_are_siblings_under_list_component():
    nodes = build_hierarchy(
        r"\begin{document}\section{List}\begin{itemize}\item First. \item Second.\end{itemize}\end{document}",
        arxiv_id="2509.21047",
    )
    items = [n for n in nodes if n.kind == "list_item"]
    assert len(items) == 2
    assert items[0].parent_id == items[1].parent_id


def test_documentclass_inside_verbatim_is_not_root(tmp_path):
    (tmp_path / "fake.tex").write_text(
        r"\begin{verbatim}\documentclass{article}\end{verbatim}\section{X}"
    )
    assert find_compilation_path(tmp_path).status == "no_root"


def test_included_content_is_inlined_at_include_position(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{Intro}
Before.
\input{middle}
After.
\end{document}
"""
    )
    (tmp_path / "middle.tex").write_text("Middle sentence.\n")
    from src.latex_parser import parse_latex_version
    parsed = parse_latex_version(tmp_path, arxiv_id="2509.21047", version=1)
    sentence_text = [n.content for n in parsed.elements if n.kind == "sentence"]
    assert sentence_text == ["Before.", "Middle sentence.", "After."]


def test_sentence_split_does_not_split_inside_inline_math():
    result = split_sentences(r"We evaluate $f(x)=1.2$ in this work. Next sentence.")
    assert len(result) == 2
    assert "$f(x)=1.2$" in result[0]
