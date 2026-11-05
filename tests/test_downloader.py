from pathlib import Path

from src.downloader import ArxivSourceDownloader


class Response:
    headers = {"Content-Type": "application/x-gzip"}

    def __init__(self, chunks, status_code=200):
        self.chunks = chunks
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        yield from self.chunks


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_requires_version_suffix(tmp_path):
    downloader = ArxivSourceDownloader(output_dir=tmp_path, user_agent="test", session=Session([]))
    try:
        downloader.download("2509.21047", "2509.21047")
    except ValueError as exc:
        assert "versioned" in str(exc)
    else:
        raise AssertionError("base ID must be rejected")


def test_streams_atomically_and_resume_checks_checksum(tmp_path):
    payload = b"not-a-tar-but-download-layer-does-not-parse"
    session = Session([Response([payload[:10], payload[10:]])])
    downloader = ArxivSourceDownloader(
        output_dir=tmp_path, user_agent="test-agent", session=session,
        delay_seconds=3, sleep=lambda _: None,
    )
    first = downloader.download("2509.21047", "2509.21047v1")
    assert first.status == "success"
    assert Path(first.archive_path).read_bytes() == payload
    second = downloader.download("2509.21047", "2509.21047v1")
    assert second.sha256 == first.sha256
    assert len(session.calls) == 1


def test_html_200_is_rejected(tmp_path):
    session = Session([Response([b"<html><body>error</body></html>"])])
    downloader = ArxivSourceDownloader(
        output_dir=tmp_path, user_agent="test-agent", session=session,
        delay_seconds=3, sleep=lambda _: None,
    )
    result = downloader.download("2509.21047", "2509.21047v1")
    assert result.status == "http_error"
    assert result.archive_path is None


def test_retries_http_429_then_succeeds(tmp_path):
    session = Session([Response([b"rate limited"], status_code=429), Response([b"payload"])])
    sleeps = []
    downloader = ArxivSourceDownloader(
        output_dir=tmp_path, user_agent="test-agent", session=session,
        delay_seconds=3, sleep=sleeps.append, jitter=lambda: 0,
    )
    result = downloader.download("2509.21047", "2509.21047v1")
    assert result.status == "success"
    assert result.attempts == 2
    assert len(session.calls) == 2
    assert sleeps[0] == 1
    assert 2.9 <= sleeps[1] <= 3.0


def test_404_is_terminal_http_error(tmp_path):
    session = Session([Response([b"not found"], status_code=404)])
    downloader = ArxivSourceDownloader(
        output_dir=tmp_path, user_agent="test-agent", session=session,
        delay_seconds=3, sleep=lambda _: None,
    )
    result = downloader.download("2509.21047", "2509.21047v1")
    assert result.status == "http_error"
    assert result.http_status == 404
