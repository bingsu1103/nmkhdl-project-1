from __future__ import annotations

import json

from src.s2_batch import crawl_references_batch
from src.s2_client import RateLimiter


class _Response:
    status_code = 200
    headers = {}

    def json(self):
        return [
            {
                "references": [
                    {
                        "paperId": "s2-1",
                        "title": "Reference one",
                        "authors": [{"name": "Alice Example"}],
                        "year": 2024,
                        "publicationDate": "2024-01-01",
                        "externalIds": {"ArXiv": "2401.00001"},
                    }
                ]
            },
            None,
        ]


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()


def test_batch_crawler_persists_same_per_paper_contract(tmp_path):
    session = _Session()
    limiter = RateLimiter(clock=lambda: 0.0, sleep=lambda _: None)
    statuses = crawl_references_batch(
        ["2509.16047", "2509.16048"],
        tmp_path,
        batch_size=10,
        session=session,
        limiter=limiter,
        max_retries=1,
    )

    assert len(session.calls) == 1
    assert session.calls[0][1]["json"]["ids"] == [
        "ARXIV:2509.16047",
        "ARXIV:2509.16048",
    ]
    assert [row["status"] for row in statuses] == ["ok", "not_found"]
    first = json.loads((tmp_path / "2509.16047.json").read_text(encoding="utf-8"))
    assert first["status"]["eligible_reference_count"] == 1
    assert first["references"][0]["ref_arxiv_id"] == "2401.00001"

    crawl_references_batch(
        ["2509.16047", "2509.16048"],
        tmp_path,
        batch_size=10,
        session=session,
        limiter=limiter,
        max_retries=1,
    )
    assert len(session.calls) == 1
