"""Unit tests for http_headers utility."""

from __future__ import annotations

import random

from findpapers.utils.http_headers import _USER_AGENTS, get_browser_headers


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
        """Accept, Accept-Language, Accept-Encoding, Connection keys must be present."""
        headers = get_browser_headers()
        for key in ("Accept", "Accept-Language", "Accept-Encoding", "Connection"):
            assert key in headers, f"Missing header: {key}"

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
