"""Unit tests for parallel task execution utilities."""

from __future__ import annotations

import time

from findpapers.utils.parallel import execute_tasks


class TestExecuteTasksSequential:
    """Tests for sequential execution (num_workers=None or 1)."""

    def test_all_items_processed(self):
        """All items yield a result."""
        results = list(execute_tasks([1, 2, 3], lambda x: x * 2, num_workers=None, timeout=None))
        values = [r for _, r, e in results if e is None]
        assert sorted(values) == [2, 4, 6]

    def test_errors_surfaced_as_third_element(self):
        """Task errors are surfaced as the exception element, not raised."""

        def _fail(x):
            raise ValueError(f"err: {x}")

        results = list(execute_tasks([1], _fail, num_workers=None, timeout=None))
        assert len(results) == 1
        item, result, error = results[0]
        assert result is None
        assert isinstance(error, ValueError)

    def test_empty_items(self):
        """Empty input yields no results."""
        results = list(execute_tasks([], lambda x: x, num_workers=None, timeout=None))
        assert results == []

    def test_timeout_stops_processing(self):
        """Global timeout stops processing remaining items."""

        def _slow(x):
            time.sleep(0.2)
            return x

        items = list(range(10))
        results = list(
            execute_tasks(items, _slow, num_workers=None, timeout=0.3, stop_on_timeout=True)
        )
        # Should process fewer than all 10 items
        assert len(results) < 10

    def test_timeout_continue_processing(self):
        """When stop_on_timeout=False all items yield a result (even on timeout)."""

        def _slow(x):
            time.sleep(0.05)
            return x

        items = list(range(3))
        results = list(
            execute_tasks(items, _slow, num_workers=None, timeout=0.03, stop_on_timeout=False)
        )
        assert len(results) == 3


class TestExecuteTasksParallel:
    """Tests for parallel execution (num_workers > 1)."""

    def test_all_items_processed_parallel(self):
        """All items are processed in parallel mode."""
        results = list(execute_tasks([1, 2, 3], lambda x: x * 3, num_workers=3, timeout=None))
        values = sorted(r for _, r, e in results if e is None)
        assert values == [3, 6, 9]

    def test_parallel_errors_surfaced(self):
        """Errors in parallel tasks are surfaced cleanly."""

        def _mixed(x):
            if x == 2:
                raise RuntimeError("boom")
            return x

        results = list(execute_tasks([1, 2, 3], _mixed, num_workers=2, timeout=None))
        errors = [e for _, _, e in results if e is not None]
        successes = [r for _, r, e in results if e is None]
        assert len(errors) == 1
        assert sorted(successes) == [1, 3]

    def test_progress_bar_not_shown_when_disabled(self):
        """No tqdm progress bar when use_progress=False."""
        results = list(
            execute_tasks(
                [1, 2],
                lambda x: x,
                num_workers=None,
                timeout=None,
                use_progress=False,
            )
        )
        assert len(results) == 2
