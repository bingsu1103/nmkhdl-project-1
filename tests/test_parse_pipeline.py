import csv
import json
from pathlib import Path

from src.parse_pipeline import run_parse_pipeline


def test_parse_pipeline_keeps_empty_versions_and_deduplicates_across_versions(tmp_path):
    data = tmp_path
    manifest = data / "manifests/source_status.jsonl"
    manifest.parent.mkdir(parents=True)
    rows = [
        {"member_id":"member-2","arxiv_id":"2509.21047","versioned_arxiv_id":"2509.21047v1","version":1,"status":"success"},
        {"member_id":"member-2","arxiv_id":"2509.21047","versioned_arxiv_id":"2509.21047v2","version":2,"status":"success"},
        {"member_id":"member-2","arxiv_id":"2509.21048","versioned_arxiv_id":"2509.21048v1","version":1,"status":"no_tex_bib"},
        {"member_id":"member-2","arxiv_id":"2509.21049","versioned_arxiv_id":"2509.21049v1","version":1,"status":"success"},
    ]
    manifest.write_text("".join(json.dumps(x)+"\n" for x in rows))
    tasks = data / "manifests/discovery/version_tasks.csv"
    tasks.parent.mkdir(parents=True)
    with tasks.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("member_id", "arxiv_id", "versioned_arxiv_id", "version"),
        )
        writer.writeheader()
        writer.writerows(
            {key: row[key] for key in writer.fieldnames}
            for row in rows
        )
    for arxiv_id, version in (("2509.21047", 1), ("2509.21047", 2), ("2509.21049", 1)):
        folder = data / f"corpus/tex/{arxiv_id}/{arxiv_id}v{version}"
        folder.mkdir(parents=True)
        (folder / "main.tex").write_text(
            r"\documentclass{article}\begin{document}\section{Intro}The same sentence.\end{document}"
        )
    result = run_parse_pipeline(data_dir=data, member_id="member-2")
    assert result["version_count"] == 4
    assert result["empty_no_tex_bib"] == 1
    elements = [json.loads(x) for x in (data/"parsed/elements.jsonl").read_text().splitlines()]
    hierarchy = [json.loads(x) for x in (data/"parsed/hierarchy.jsonl").read_text().splitlines()]
    sentence_rows = [x for x in elements if x["kind"] == "sentence"]
    assert len(sentence_rows) == 2  # dedup within a paper's versions, not across papers
    sentence_id = next(x["element_id"] for x in sentence_rows if x["arxiv_id"] == "2509.21047")
    assert sum(x["element_id"] == sentence_id for x in hierarchy) == 2
    assert result["contract_reconciliation"]["is_complete"] is True

    first_elements = (data / "parsed/elements.jsonl").read_bytes()
    resumed = run_parse_pipeline(data_dir=data, member_id="member-2", resume=True)
    assert resumed["resumed_versions"] == 4
    assert (data / "parsed/elements.jsonl").read_bytes() == first_elements


def test_parse_checkpoint_invalidates_when_source_fingerprint_changes(tmp_path):
    data = tmp_path
    tasks = data / "manifests/discovery/version_tasks.csv"
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
    manifest = data / "manifests/source_status.jsonl"
    source = data / "corpus/tex/2509.16047/2509.16047v1"
    source.mkdir(parents=True)
    (source / "main.tex").write_text(
        r"\documentclass{article}\begin{document}First.\end{document}",
        encoding="utf-8",
    )

    def write_status(digest: str) -> None:
        manifest.write_text(
            json.dumps(
                {
                    "member_id": "member-1",
                    "arxiv_id": "2509.16047",
                    "versioned_arxiv_id": "2509.16047v1",
                    "version": 1,
                    "status": "success",
                    "download": {"sha256": "archive"},
                    "extraction": {
                        "files": [
                            {"path": "main.tex", "sha256": digest, "bytes": 63}
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    write_status("source-one")
    first = run_parse_pipeline(data_dir=data, member_id="member-1")
    assert first["resumed_versions"] == 0
    second = run_parse_pipeline(data_dir=data, member_id="member-1")
    assert second["resumed_versions"] == 1

    write_status("source-two")
    invalidated = run_parse_pipeline(data_dir=data, member_id="member-1")
    assert invalidated["resumed_versions"] == 0
