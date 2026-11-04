from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import requests

from src.arxiv_client import (
    DiscoveryError,
    InMemoryArxivClient,
    LiveArxivClient,
    MalformedDiscoveryResponseError,
    PaperNotFoundError,
    TransientDiscoveryError,
)
from src.contracts import PaperMetadata


class InMemoryArxivClientTests(unittest.TestCase):
    def test_returns_unicode_metadata_without_reordering_authors(self) -> None:
        metadata = PaperMetadata(
            arxiv_id="2509.16047",
            latest_versioned_id="2509.16047v1",
            title="Dữ liệu thử nghiệm",
            authors=("Ngô Gia An", "Example Author"),
            submission_date="2025-09-01",
        )
        client = InMemoryArxivClient({metadata.arxiv_id: metadata})

        actual = client.discover(metadata.arxiv_id)

        self.assertEqual(actual, metadata)
        self.assertEqual(actual.authors, ("Ngô Gia An", "Example Author"))
        self.assertEqual(client.calls, [metadata.arxiv_id])

    def test_missing_record_is_explicit_not_found(self) -> None:
        client = InMemoryArxivClient({})
        with self.assertRaisesRegex(PaperNotFoundError, "not found"):
            client.discover("2509.99999")


class LiveArxivClientTests(unittest.TestCase):
    FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>https://arxiv.org/abs/2509.16047v2</id>
    <updated>2025-09-10T12:00:00Z</updated>
    <published>2025-09-01T08:00:00Z</published>
    <title>  D\xe1\xbb\xaf li\xe1\xbb\x87u\n th\xe1\xbb\xad nghi\xe1\xbb\x87m  </title>
    <author><name>Ng\xc3\xb4 Gia An</name></author>
    <author><name>Example Author</name></author>
    <arxiv:journal_ref>Example Venue</arxiv:journal_ref>
  </entry>
</feed>'''

    class Response:
        def __init__(self, status: int, content: bytes = b"", headers=None) -> None:
            self.status_code = status
            self.content = content
            self.headers = headers or {}

    class Session:
        def __init__(self, responses) -> None:
            self.responses = list(responses)
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    def test_maps_atom_metadata_and_caches_raw_response(self) -> None:
        session = self.Session([self.Response(200, self.FEED)])
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory), session)
            first = client.discover("2509.16047")
            second = client.discover("2509.16047")

            self.assertEqual(first, second)
            self.assertEqual(first.latest_versioned_id, "2509.16047v2")
            self.assertEqual(first.title, "Dữ liệu thử nghiệm")
            self.assertEqual(first.authors, ("Ngô Gia An", "Example Author"))
            self.assertEqual(first.revised_dates, ("2025-09-10",))
            self.assertEqual(first.venue, "Example Venue")
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(session.calls[0][1]["timeout"], 30.0)
            self.assertIn("group-18", session.calls[0][1]["headers"]["User-Agent"])

    def test_empty_feed_is_not_found(self) -> None:
        empty = b'<feed xmlns="http://www.w3.org/2005/Atom" />'
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory), self.Session([self.Response(200, empty)]))
            with self.assertRaises(PaperNotFoundError):
                client.discover("2509.99999")

    def test_retries_rate_limit_using_retry_after(self) -> None:
        sleeps = []
        session = self.Session([
            self.Response(429, headers={"Retry-After": "7"}),
            self.Response(200, self.FEED),
        ])
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory), session, sleep=sleeps.append)
            client.discover("2509.16047")
        self.assertIn(7.0, sleeps)
        self.assertEqual(len(session.calls), 2)

    def test_exhausted_timeout_is_transient(self) -> None:
        session = self.Session([
            requests.Timeout("one"),
            requests.Timeout("two"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory), session, max_attempts=2)
            with self.assertRaises(TransientDiscoveryError):
                client.discover("2509.16047")

    def test_permanent_http_does_not_retry(self) -> None:
        session = self.Session([self.Response(400)])
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory), session)
            with self.assertRaises(DiscoveryError):
                client.discover("2509.16047")
        self.assertEqual(len(session.calls), 1)

    def test_rejects_malformed_or_unexpected_feed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed = self._client(
                Path(directory), self.Session([self.Response(200, b"not-xml")])
            )
            with self.assertRaises(MalformedDiscoveryResponseError):
                malformed.discover("2509.16047")

    def test_rejects_unsafe_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "at least 3"):
                LiveArxivClient(
                    user_agent="group-18",
                    cache_dir=directory,
                    delay_seconds=2.9,
                )

    def _client(self, cache: Path, session, *, sleep=lambda _: None, max_attempts=4):
        ticks = iter(range(1000))
        return LiveArxivClient(
            user_agent="group-18-arxiv-project/0.2 (contact: repository owner)",
            cache_dir=cache,
            session=session,
            clock=lambda: float(next(ticks)),
            sleep=sleep,
            jitter=lambda: 0.0,
            max_attempts=max_attempts,
        )


if __name__ == "__main__":
    unittest.main()
