import io
import tarfile
from pathlib import Path

import pytest

from src.extractor import SafeSourceExtractor


def make_tar(path: Path, entries):
    with tarfile.open(path, "w:gz") as tar:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "../outside.tex"
                tar.addfile(info)
            else:
                tar.addfile(info, io.BytesIO(data))


def test_extracts_only_tex_bib_and_preserves_bytes(tmp_path):
    archive = tmp_path / "src.tar.gz"
    tex = b"\\documentclass{article}\n\\begin{document}Hi\\end{document}\n"
    bib = b"@article{x, title={A}}"
    make_tar(archive, [
        ("paper/main.tex", tex, "file"),
        ("paper/refs.bib", bib, "file"),
        ("paper/figure.png", b"PNG", "file"),
        ("paper/style.sty", b"sty", "file"),
    ])
    result = SafeSourceExtractor(output_dir=tmp_path / "out").extract(
        archive, arxiv_id="2509.21047", versioned_arxiv_id="2509.21047v1"
    )
    assert result.status == "success"
    assert {f.path for f in result.files} == {"paper/main.tex", "paper/refs.bib"}
    out = tmp_path / "out/2509.21047/2509.21047v1"
    assert (out / "paper/main.tex").read_bytes() == tex
    assert (out / "paper/refs.bib").read_bytes() == bib
    assert result.filtered_bytes == len(tex) + len(bib)


@pytest.mark.parametrize("bad", ["../evil.tex", "/tmp/evil.tex", "C:\\\\evil.tex", "a\\\\..\\\\evil.tex"])
def test_rejects_unsafe_paths(tmp_path, bad):
    archive = tmp_path / "bad.tar.gz"
    make_tar(archive, [(bad, b"bad", "file")])
    result = SafeSourceExtractor(output_dir=tmp_path / "out").extract(
        archive, arxiv_id="2509.21047", versioned_arxiv_id="2509.21047v1"
    )
    assert result.status == "invalid_archive"
    assert not (tmp_path / "evil.tex").exists()


def test_symlink_not_extracted(tmp_path):
    archive = tmp_path / "links.tar.gz"
    make_tar(archive, [("link.tex", b"", "symlink"), ("ok.tex", b"hello", "file")])
    result = SafeSourceExtractor(output_dir=tmp_path / "out").extract(
        archive, arxiv_id="2509.21047", versioned_arxiv_id="2509.21047v1"
    )
    assert result.status == "success"
    assert [f.path for f in result.files] == ["ok.tex"]


def test_no_tex_bib_is_terminal_empty_record(tmp_path):
    archive = tmp_path / "only-image.tar.gz"
    make_tar(archive, [("figure.png", b"PNG", "file")])
    result = SafeSourceExtractor(output_dir=tmp_path / "out").extract(
        archive, arxiv_id="2509.21047", versioned_arxiv_id="2509.21047v1"
    )
    assert result.status == "no_tex_bib"
    assert result.files == ()
