"""Unit tests for http_headers utility."""

from __future__ import annotations

import random

from findpapers.utils.http_headers import (
    _CHROME_CLIENT_HINTS,
    _SEC_FETCH_HEADERS,
    _USER_AGENTS,
    _client_hints_for_ua,
    get_browser_headers,
)


class TestGetBrowserHeaders:
    """Tests for get_browser_headers()."""

    def test_returns_dict(self) -> None:
        """Return value is a non-empty dict."""
        headers = get_browser_headers()
        assert isinstance(headers, dict)
        assert headers

    def test_user_agent_present(self) -> None:
        """Returned headers always contain a User-Agent key."""
        headers = get_browser_headers()
        assert "User-Agent" in headers

    def test_user_agent_is_not_python_requests(self) -> None:
        """User-Agent must not expose the python-requests fingerprint."""
        for _ in range(20):
            headers = get_browser_headers()
            assert "python-requests" not in headers["User-Agent"].lower()

    def test_user_agent_starts_with_mozilla(self) -> None:
        """All pool entries start with 'Mozilla/' as real browsers do."""
        for ua in _USER_AGENTS:
            assert ua.startswith("Mozilla/"), f"Bad UA: {ua}"

    def test_required_headers_present(self) -> None:
        """Accept, Accept-Language, Connection keys must be present.

        Accept-Encoding is intentionally omitted from the dict so that httpx
        can add it and handle decompression automatically (passing it explicitly
        disables httpx auto-decompression, causing Brotli responses to be
        returned as raw binary).
        """
        headers = get_browser_headers()
        for key in ("Accept", "Accept-Language", "Connection"):
            assert key in headers, f"Missing header: {key}"
        assert "Accept-Encoding" not in headers, (
            "Accept-Encoding must NOT be set manually — httpx manages it"
        )

    def test_sec_fetch_headers_present(self) -> None:
        """Sec-Fetch-* and Cache-Control headers must always be included."""
        headers = get_browser_headers()
        for key in _SEC_FETCH_HEADERS:
            assert key in headers, f"Missing Sec-Fetch header: {key}"
            assert headers[key] == _SEC_FETCH_HEADERS[key]

    def test_sec_fetch_dest_is_document(self) -> None:
        """Sec-Fetch-Dest must be 'document' to simulate page navigation."""
        assert get_browser_headers()["Sec-Fetch-Dest"] == "document"

    def test_sec_fetch_mode_is_navigate(self) -> None:
        """Sec-Fetch-Mode must be 'navigate'."""
        assert get_browser_headers()["Sec-Fetch-Mode"] == "navigate"

    def test_sec_fetch_site_is_none(self) -> None:
        """Sec-Fetch-Site must be 'none' (direct navigation — no referring site)."""
        assert get_browser_headers()["Sec-Fetch-Site"] == "none"

    def test_rotation_uses_multiple_agents(self) -> None:
        """Over many calls, more than one distinct User-Agent should be returned."""
        agents = {get_browser_headers()["User-Agent"] for _ in range(200)}
        assert len(agents) > 1, "Expected headers to rotate across multiple User-Agents"

    def test_seeded_rng_is_deterministic(self) -> None:
        """With a fixed seed the same User-Agent is always returned."""
        rng = random.Random(42)
        first = get_browser_headers(rng=rng)["User-Agent"]
        rng.seed(42)
        second = get_browser_headers(rng=rng)["User-Agent"]
        assert first == second

    def test_custom_rng_chooses_from_pool(self) -> None:
        """Whatever rng picks, the User-Agent must come from the pool."""
        rng = random.Random(0)
        for _ in range(len(_USER_AGENTS) * 3):
            ua = get_browser_headers(rng=rng)["User-Agent"]
            assert ua in _USER_AGENTS, f"Unknown User-Agent returned: {ua}"

    def test_pool_has_at_least_five_entries(self) -> None:
        """The UA pool must have at least 5 entries for meaningful rotation."""
        assert len(_USER_AGENTS) >= 5

    def test_all_pool_entries_are_unique(self) -> None:
        """No duplicate User-Agent strings in the pool."""
        assert len(_USER_AGENTS) == len(set(_USER_AGENTS))

    def test_each_call_returns_independent_dict(self) -> None:
        """Mutating the returned dict must not affect subsequent calls."""
        headers1 = get_browser_headers()
        headers1["User-Agent"] = "tampered"
        headers2 = get_browser_headers()
        assert headers2["User-Agent"] != "tampered"

    def test_chrome_ua_includes_client_hints(self) -> None:
        """Chrome User-Agent strings must trigger sec-ch-ua Client Hints."""
        chrome_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
        hints = _client_hints_for_ua(chrome_ua)
        assert "sec-ch-ua" in hints
        assert "sec-ch-ua-mobile" in hints
        assert "sec-ch-ua-platform" in hints
        assert "Google Chrome" in hints["sec-ch-ua"]

    def test_edge_ua_includes_client_hints(self) -> None:
        """Edge User-Agent strings must trigger sec-ch-ua Client Hints."""
        edge_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
        )
        hints = _client_hints_for_ua(edge_ua)
        assert "sec-ch-ua" in hints
        assert "Microsoft Edge" in hints["sec-ch-ua"]

    def test_firefox_ua_has_no_client_hints(self) -> None:
        """Firefox does not send sec-ch-ua — no hints expected for Firefox UAs."""
        firefox_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
        )
        hints = _client_hints_for_ua(firefox_ua)
        assert hints == {}

    def test_safari_ua_has_no_client_hints(self) -> None:
        """Safari does not send sec-ch-ua — no hints expected for Safari UAs."""
        safari_ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.2 Safari/605.1.15"
        )
        hints = _client_hints_for_ua(safari_ua)
        assert hints == {}

    def test_chrome_headers_include_client_hints(self) -> None:
        """get_browser_headers() includes sec-ch-ua when a Chrome UA is selected."""
        # Verify that at least one Chrome UA is in the pool, then call the
        # helper directly instead of monkey-patching the RNG.
        chrome_uas = [
            ua for ua in _USER_AGENTS if "Chrome/" in ua and "Edg/" not in ua and "Chrome/12" in ua
        ]
        assert chrome_uas, "No Chrome UA in pool to test"
        hints = _client_hints_for_ua(chrome_uas[0])
        assert "sec-ch-ua" in hints

    def test_chrome_client_hints_pool_is_populated(self) -> None:
        """_CHROME_CLIENT_HINTS must define hints for at least 2 Chrome versions."""
        assert len(_CHROME_CLIENT_HINTS) >= 2
