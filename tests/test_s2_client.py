"""
Test suite cho Semantic Scholar client (s2_client.py).
Thuộc sở hữu của Member 3 - Semantic Scholar, BibTeX và Reference Dedup.
Chỉ dùng response synthetic, không gọi API thật.
"""

import json

import pytest
import requests

from src.s2_client import (
    S2_FIELDS,
    STATUS_CLIENT_ERROR,
    STATUS_MALFORMED_JSON,
    STATUS_NETWORK_ERROR,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_RATE_LIMITED,
    STATUS_SCHEMA_ERROR,
    STATUS_SERVER_ERROR,
    RateLimiter,
    build_raw_records,
    build_references_rows,
    crawl_references,
    extract_ref_arxiv_id,
    fetch_paper_references,
    load_raw_references,
    summarize_s2_crawl,
    to_eligible_records,
)
from src.storage import REFERENCES_SCHEMA, create_table_from_records
from src.validate import validate_references_table


# ---------- Fake objects ----------

class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, sec):
        self.sleeps.append(sec)
        self.now += sec


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("invalid json")
        return self._payload


class FakeSession:
    """Trả lần lượt các response cho trước; phần tử là Exception thì raise."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def fast_limiter():
    clock = FakeClock()
    return RateLimiter(clock=clock, sleep=clock.sleep)


def ok_payload(refs):
    return FakeResponse(200, {"references": refs})


SAMPLE_REFS = [
    {"paperId": "s2a", "title": "Attention Is All You Need", "authors": [{"name": "A. Vaswani"}],
     "year": 2017, "publicationDate": "2017-06-12", "externalIds": {"ArXiv": "1706.03762", "DOI": "10.x/1"}},
    {"paperId": "s2b", "title": "A Book", "authors": [], "year": 1999, "publicationDate": None,
     "externalIds": {"DOI": "10.x/2"}},  # không có arXiv -> chỉ giữ ở raw
    {"paperId": None, "title": None, "authors": None, "year": None, "publicationDate": None,
     "externalIds": None},  # thiếu hết field -> vẫn giữ ở raw
    {"paperId": "s2c", "title": "Old paper", "authors": [{"name": "E. Witten"}], "year": 1999,
     "publicationDate": None, "externalIds": {"ArXiv": "hep-th/9901001"}},
    "not-a-dict",  # malformed item
]


# ---------- T01: Query contract ----------

def test_query_contract_url_params_and_no_key():
    session = FakeSession([ok_payload([])])
    fetch_paper_references("2310.12345v3", session=session, limiter=fast_limiter())
    call = session.calls[0]
    assert call["url"] == "https://api.semanticscholar.org/graph/v1/paper/arXiv:2310.12345"
    assert call["params"] == {"fields": S2_FIELDS}
    assert "references.externalIds" in S2_FIELDS
    assert "references.authors.name" not in S2_FIELDS  # không dùng nested field
    assert call["headers"] == {}  # anonymous mode
    assert call["timeout"] is not None


def test_api_key_from_env_only_in_header(tmp_path, monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "secret-key-123")
    session = FakeSession([ok_payload(SAMPLE_REFS[:1])])
    crawl_references(["2310.12345"], tmp_path, session=session, limiter=fast_limiter())
    assert session.calls[0]["headers"] == {"x-api-key": "secret-key-123"}
    for f in tmp_path.iterdir():
        assert "secret-key-123" not in f.read_text(encoding="utf-8")


# ---------- T02: Rate limit và retry ----------

def test_rate_limiter_one_request_per_second():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    times = []
    for _ in range(5):
        limiter.wait()
        times.append(clock.now)
    assert all(b - a >= 1.0 for a, b in zip(times, times[1:]))


def test_rate_limiter_100_requests_per_5_minutes():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    times = []
    for _ in range(201):
        limiter.wait()
        times.append(clock.now)
    # Request thứ 101 phải chờ tới khi request đầu tiên ra khỏi cửa sổ 300s
    assert times[100] - times[0] >= 300.0
    # Mọi cửa sổ 300s bất kỳ chứa không quá 100 request
    for i in range(len(times) - 100):
        assert times[i + 100] - times[i] >= 300.0


def test_429_honors_retry_after():
    clock = FakeClock()
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "7"}), ok_payload([])])
    res = fetch_paper_references("2310.12345", session=session, limiter=fast_limiter(), sleep=clock.sleep)
    assert res["status"] == STATUS_OK
    assert res["attempts"] == 2
    assert clock.sleeps == [7.0]


def test_429_exhausted_is_rate_limited():
    clock = FakeClock()
    session = FakeSession([FakeResponse(429)] * 3)
    res = fetch_paper_references("2310.12345", session=session, limiter=fast_limiter(),
                                 max_retries=3, sleep=clock.sleep)
    assert res["status"] == STATUS_RATE_LIMITED
    assert len(session.calls) == 3


def test_5xx_retries_are_bounded_with_backoff():
    clock = FakeClock()
    session = FakeSession([FakeResponse(503)] * 3)
    res = fetch_paper_references("2310.12345", session=session, limiter=fast_limiter(),
                                 max_retries=3, sleep=clock.sleep)
    assert res["status"] == STATUS_SERVER_ERROR
    assert res["attempts"] == 3 and len(session.calls) == 3
    assert len(clock.sleeps) == 2  # không sleep sau lần thử cuối
    # backoff 2^(n-1) + jitter [0, 1): lần 1 trong [1, 2), lần 2 trong [2, 3)
    assert 1.0 <= clock.sleeps[0] < 2.0 and 2.0 <= clock.sleeps[1] < 3.0


def test_5xx_then_success():
    clock = FakeClock()
    session = FakeSession([FakeResponse(500), ok_payload(SAMPLE_REFS[:1])])
    res = fetch_paper_references("2310.12345", session=session, limiter=fast_limiter(), sleep=clock.sleep)
    assert res["status"] == STATUS_OK and len(res["references"]) == 1


def test_timeout_is_network_error():
    clock = FakeClock()
    session = FakeSession([requests.Timeout("t")] * 2)
    res = fetch_paper_references("2310.12345", session=session, limiter=fast_limiter(),
                                 max_retries=2, sleep=clock.sleep)
    assert res["status"] == STATUS_NETWORK_ERROR
    assert res["error"] == "Timeout"
    assert len(session.calls) == 2


def test_404_not_found_no_retry():
    session = FakeSession([FakeResponse(404)])
    res = fetch_paper_references("2310.12345", session=session, limiter=fast_limiter())
    assert res["status"] == STATUS_NOT_FOUND
    assert len(session.calls) == 1


def test_400_client_error_no_retry():
    session = FakeSession([FakeResponse(400)])
    res = fetch_paper_references("2310.12345", session=session, limiter=fast_limiter())
    assert res["status"] == STATUS_CLIENT_ERROR
    assert len(session.calls) == 1


def test_invalid_json_and_schema_error():
    res = fetch_paper_references("2310.12345", session=FakeSession([FakeResponse(200, bad_json=True)]),
                                 limiter=fast_limiter())
    assert res["status"] == STATUS_MALFORMED_JSON

    res = fetch_paper_references("2310.12345", session=FakeSession([FakeResponse(200, {"references": "x"})]),
                                 limiter=fast_limiter())
    assert res["status"] == STATUS_SCHEMA_ERROR

    res = fetch_paper_references("2310.12345", session=FakeSession([FakeResponse(200, ["x"])]),
                                 limiter=fast_limiter())
    assert res["status"] == STATUS_SCHEMA_ERROR


def test_200_empty_or_null_references():
    for payload in ({"references": []}, {"references": None}):
        res = fetch_paper_references("2310.12345", session=FakeSession([FakeResponse(200, payload)]),
                                     limiter=fast_limiter())
        assert res["status"] == STATUS_OK
        assert res["references"] == []


# ---------- T04: Chuẩn hóa arXiv ID ----------

@pytest.mark.parametrize("external_ids, expected", [
    ({"ArXiv": "1706.03762"}, "1706.03762"),            # modern 4 số
    ({"ArXiv": "2310.12345"}, "2310.12345"),            # modern 5 số
    ({"ArXiv": "2310.12345v2"}, "2310.12345"),          # có version
    ({"ArXiv": "hep-th/9901001"}, "hep-th/9901001"),    # old-style
    ({"ArXiv": "math.GT/0309136v1"}, "math.GT/0309136"),  # old-style có subject class + version
    ({"ArXiv": "arXiv:1706.03762"}, "1706.03762"),      # có prefix
    ({"ArXiv": "garbage"}, None),                       # malformed
    ({"ArXiv": "10.1000/xyz"}, None),                   # DOI nhét nhầm vào field ArXiv
    ({"ArXiv": ""}, None),                              # rỗng
    ({"DOI": "10.1000/xyz", "MAG": "123"}, None),       # không có ArXiv, không suy từ DOI
    ({"DOI": "10.1/x", "ArXiv": "1810.04805", "CorpusId": 1}, "1810.04805"),  # nhiều external IDs
    (None, None),
])
def test_extract_ref_arxiv_id(external_ids, expected):
    raw, normalized = extract_ref_arxiv_id(external_ids)
    assert normalized == expected
    if external_ids and external_ids.get("ArXiv"):
        assert raw == external_ids["ArXiv"]  # luôn giữ raw value để audit


# ---------- T03: Lưu toàn bộ raw references ----------

def test_raw_records_keep_every_reference():
    records, parse_failures = build_raw_records("2310.12345", SAMPLE_REFS)
    # raw count = response count - malformed item
    assert len(records) == len(SAMPLE_REFS) - 1
    assert parse_failures == 1
    # Ref không có arXiv ID và ref thiếu field vẫn được giữ, kèm S2 object gốc
    assert records[1]["ref_arxiv_id"] is None and records[1]["s2"]["paperId"] == "s2b"
    assert records[2]["s2"]["title"] is None


def test_crawl_writes_status_and_raw_file(tmp_path):
    session = FakeSession([ok_payload(SAMPLE_REFS)])
    statuses = crawl_references(["2310.12345v2"], tmp_path, session=session, limiter=fast_limiter())
    st = statuses[0]
    assert st["arxiv_id"] == "2310.12345"
    assert st["status"] == STATUS_OK
    assert st["response_reference_count"] == 5
    assert st["raw_reference_count"] == 4
    assert st["parse_failures"] == 1
    assert st["eligible_reference_count"] == 2
    assert st["queried_at"].endswith("Z")

    saved = json.loads((tmp_path / "2310.12345.json").read_text(encoding="utf-8"))
    assert saved["status"] == st
    assert len(saved["references"]) == 4
    assert not list(tmp_path.glob("*.tmp"))  # atomic write không để lại file tạm


def test_old_style_citing_id_file_name(tmp_path):
    session = FakeSession([ok_payload([])])
    crawl_references(["hep-th/9901001"], tmp_path, session=session, limiter=fast_limiter())
    assert session.calls[0]["url"].endswith("arXiv:hep-th/9901001")
    assert (tmp_path / "hep-th_9901001.json").exists()


def test_resume_skips_done_and_retries_failed(tmp_path):
    clock = FakeClock()
    first = FakeSession([ok_payload(SAMPLE_REFS), FakeResponse(404), FakeResponse(503)])
    crawl_references(["2310.00001", "2310.00002", "2310.00003"], tmp_path, session=first,
                     limiter=fast_limiter(), max_retries=1, sleep=clock.sleep)

    # Rerun: chỉ paper lỗi (503) được gọi lại; ok và not_found dùng cache
    second = FakeSession([ok_payload(SAMPLE_REFS[:1])])
    statuses = crawl_references(["2310.00001", "2310.00002", "2310.00003"], tmp_path, session=second,
                                limiter=fast_limiter(), max_retries=1, sleep=clock.sleep)
    assert len(second.calls) == 1
    assert second.calls[0]["url"].endswith("2310.00003")
    assert [s["status"] for s in statuses] == [STATUS_OK, STATUS_NOT_FOUND, STATUS_OK]

    # Không append trùng khi rerun
    raw = load_raw_references(tmp_path)
    assert len(raw) == 4 + 1


def test_duplicate_input_ids_queried_once(tmp_path):
    session = FakeSession([ok_payload([])])
    statuses = crawl_references(["2310.12345v1", "2310.12345v2"], tmp_path, session=session,
                                limiter=fast_limiter())
    assert len(session.calls) == 1 and len(statuses) == 1


# ---------- T05: Mapping cho bảng references ----------

def test_eligible_mapping_fields():
    records, _ = build_raw_records("2310.12345", SAMPLE_REFS)
    eligible = to_eligible_records(records)
    assert [e["ref_arxiv_id"] for e in eligible] == ["1706.03762", "hep-th/9901001"]
    first = eligible[0]
    assert set(first) == set(REFERENCES_SCHEMA.names)
    assert first["arxiv_id"] == "2310.12345"
    assert first["ref_title"] == "Attention Is All You Need"
    assert first["ref_authors"] == ["A. Vaswani"]
    assert first["ref_submission_date"] == "2017-06-12T00:00:00Z"
    assert first["ref_s2_id"] == "s2a"


def test_year_is_not_used_as_submission_date():
    records, _ = build_raw_records("2310.12345", SAMPLE_REFS)
    rows, _ = build_references_rows(records)
    old = [r for r in rows if r["ref_arxiv_id"] == "hep-th/9901001"][0]
    assert old["ref_submission_date"] is None  # chỉ có year=1999, không bịa ngày


def test_rows_pass_references_validation():
    refs = SAMPLE_REFS + [dict(SAMPLE_REFS[0], paperId="s2a-dup")]  # duplicate ref arXiv ID
    records, _ = build_raw_records("2310.12345", refs)
    rows, duplicates = build_references_rows(records)
    assert duplicates == 1
    table = create_table_from_records(rows, REFERENCES_SCHEMA)
    assert validate_references_table(table).is_valid


# ---------- T06: Metrics ----------

def test_summary_counts_and_denominators(tmp_path):
    clock = FakeClock()
    refs = SAMPLE_REFS + [dict(SAMPLE_REFS[0], paperId="dup"), {"externalIds": {"ArXiv": "garbage"}}]
    session = FakeSession([ok_payload(refs), FakeResponse(404), FakeResponse(503)])
    statuses = crawl_references(["2310.00001", "2310.00002", "2310.00003"], tmp_path, session=session,
                                limiter=fast_limiter(), max_retries=1, sleep=clock.sleep)
    summary = summarize_s2_crawl(statuses, load_raw_references(tmp_path))

    assert summary["s2_citing_papers_attempted"] == 3
    assert summary["s2_citing_papers_succeeded"] == 1
    assert summary["s2_citing_papers_not_indexed"] == 1
    assert summary["s2_citing_papers_failed"] == 1
    assert summary["raw_references_total"] == 6
    assert summary["raw_parse_failures"] == 1
    assert summary["references_missing_arxiv_id"] == 2
    assert summary["references_invalid_arxiv_id"] == 1
    assert summary["eligible_references_before_dedup"] == 3
    assert summary["duplicate_references"] == 1
    assert summary["eligible_references_final"] == 2
    assert summary["eligible_missing_submission_date"] == 1
    assert summary["avg_all_references_per_paper"] == 6.0
    assert summary["avg_eligible_arxiv_references_per_paper"] == 2.0
    assert summary["reference_metadata_success_rate"] == {"numerator": 1, "denominator": 3, "value": 0.3333}
