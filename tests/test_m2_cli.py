from __future__ import annotations

import contextlib
import csv
import io
import json
from pathlib import Path

from src.cli import main


def test_run_parsing_builds_and_validates_all_three_m2_tables(tmp_path: Path) -> None:
    tasks = tmp_path / "manifests/discovery/version_tasks.csv"
    tasks.parent.mkdir(parents=True)
    with tasks.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("member_id", "arxiv_id", "versioned_arxiv_id", "version"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "member_id": "member-1",
                "arxiv_id": "2509.16047",
                "versioned_arxiv_id": "2509.16047v1",
                "version": 1,
            }
        )
    status = {
        "member_id": "member-1",
        "arxiv_id": "2509.16047",
        "versioned_arxiv_id": "2509.16047v1",
        "version": 1,
        "status": "success",
        "download": {"sha256": "archive"},
        "extraction": {
            "files": [
                {"path": "main.tex", "sha256": "main", "bytes": 1},
                {"path": "refs.bib", "sha256": "bib", "bytes": 1},
            ]
        },
    }
    (tmp_path / "manifests/source_status.jsonl").write_text(
        json.dumps(status) + "\n", encoding="utf-8"
    )
    source = tmp_path / "corpus/tex/2509.16047/2509.16047v1"
    source.mkdir(parents=True)
    (source / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{Introduction}
This is a complete sentence.
\begin{equation}x = y + 1\end{equation}
\begin{itemize}\item First item.\end{itemize}
\bibliography{refs}
\end{document}
""",
        encoding="utf-8",
    )
    (source / "refs.bib").write_text(
        "@article{example, title={A Complete Reference Title}, "
        "author={Example, Alice}, year={2020}}",
        encoding="utf-8",
    )

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = main(
            [
                "run-parsing",
                "--data-dir",
                str(tmp_path),
                "--member",
                "member-1",
            ]
        )

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["is_success"] is True
    assert payload["standardization"]["unified_entries"] == 1
    assert payload["tables"]["row_counts"]["bibtex"] == 1
    assert payload["validation"]["is_valid"] is True
    assert payload["parser"]["kind_counts"]["formula"] == 1
    assert payload["parser"]["kind_counts"]["item"] == 1
    assert (tmp_path / "tables/elements/part-00000.parquet").is_file()
    assert (tmp_path / "tables/hierarchy/part-00000.parquet").is_file()
    assert (tmp_path / "tables/bibtex/part-00000.parquet").is_file()
