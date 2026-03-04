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
        assert sorted(v for v in values if v is not None) == [2, 4, 6]

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
        results: list[tuple[int, int | None, Exception | None]] = list(
            execute_tasks([], lambda x: x, num_workers=None, timeout=None)
        )
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
        values = sorted(r for _, r, e in results if e is None and r is not None)
        assert values == [3, 6, 9]

    def test_parallel_errors_surfaced(self):
        """Errors in parallel tasks are surfaced cleanly."""

        def _mixed(x):
            if x == 2:
                raise RuntimeError("boom")
            return x

        results = list(execute_tasks([1, 2, 3], _mixed, num_workers=2, timeout=None))
        errors = [e for _, _, e in results if e is not None]
        successes = [r for _, r, e in results if e is None and r is not None]
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

    def test_parallel_timeout_yields_remaining_as_timeout_errors(self):
        """When global timeout fires in parallel mode, remaining items yield TimeoutError."""
        import time

        def _slow(x):
            time.sleep(0.5)
            return x

        items = list(range(4))
        results = list(execute_tasks(items, _slow, num_workers=4, timeout=0.05))
        # All items must be yielded (either as timeout errors or fast completions)
        assert len(results) == len(items)
        errors = [e for _, _, e in results if e is not None]
        assert len(errors) > 0
        for _, _, e in results:
            if e is not None:
                assert isinstance(e, TimeoutError)

    def test_parallel_timeout_done_future_yields_result(self):
        """Done futures not yet yielded are resolved when global timeout fires."""
        from concurrent.futures import Future
        from concurrent.futures import TimeoutError as FuturesTimeoutError
        from unittest.mock import MagicMock, patch

        # Build two futures: one already done (result=99), one not done
        done_future: Future = Future()
        done_future.set_result(99)
        not_done_future: Future = Future()  # never completed

        items = ["a", "b"]
        item_to_future = {"a": done_future, "b": not_done_future}

        # Make as_completed raise FuturesTimeoutError immediately (no futures yielded)
        def _fake_as_completed(fs, timeout=None):
            raise FuturesTimeoutError()

        with (
            patch("findpapers.utils.parallel.as_completed", side_effect=_fake_as_completed),
            patch("findpapers.utils.parallel.ThreadPoolExecutor") as mock_executor_cls,
        ):
            mock_executor = MagicMock()
            mock_executor_cls.return_value.__enter__.return_value = mock_executor
            mock_executor.submit.side_effect = lambda fn, item: item_to_future[item]
            results = list(
                execute_tasks(items, lambda x: x, num_workers=2, timeout=0.01, use_progress=False)
            )

        assert len(results) == 2

    def test_parallel_timeout_done_future_with_exception(self):
        """Done futures that raise exceptions are surfaced correctly after timeout."""
        from concurrent.futures import Future
        from concurrent.futures import TimeoutError as FuturesTimeoutError
        from unittest.mock import MagicMock, patch

        boom_future: Future = Future()
        boom_future.set_exception(ValueError("boom"))

        items = ["x"]

        def _fake_as_completed(fs, timeout=None):
            raise FuturesTimeoutError()

        with (
            patch("findpapers.utils.parallel.as_completed", side_effect=_fake_as_completed),
            patch("findpapers.utils.parallel.ThreadPoolExecutor") as mock_executor_cls,
        ):
            mock_executor = MagicMock()
            mock_executor_cls.return_value.__enter__.return_value = mock_executor
            mock_executor.submit.side_effect = lambda fn, item: boom_future
            results = list(
                execute_tasks(items, lambda x: x, num_workers=2, timeout=0.01, use_progress=False)
            )

        assert len(results) == 1
        _, result, error = results[0]
        assert result is None
        assert isinstance(error, ValueError)
