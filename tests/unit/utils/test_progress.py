"""Unit tests for the progress bar utility."""

from __future__ import annotations

from tqdm import tqdm

from findpapers.utils.progress import make_progress_bar


class TestMakeProgressBar:
    """Tests for :func:`~findpapers.utils.progress.make_progress_bar`."""

    def test_returns_tqdm_instance(self):
        """make_progress_bar returns a tqdm object."""
        pbar = make_progress_bar()
        assert isinstance(pbar, tqdm)
        pbar.close()

    def test_leave_defaults_to_true(self):
        """The returned bar has leave=True by default."""
        pbar = make_progress_bar()
        assert pbar.leave is True
        pbar.close()

    def test_leave_false_is_forwarded(self):
        """Passing leave=False creates a transient bar."""
        pbar = make_progress_bar(leave=False)
        assert pbar.leave is False
        pbar.close()

    def test_desc_is_set(self):
        """The desc parameter is forwarded to tqdm."""
        pbar = make_progress_bar(desc="MyDesc")
        assert pbar.desc == "MyDesc"
        pbar.close()

    def test_desc_is_none_by_default(self):
        """When no desc is provided the bar has no description."""
        pbar = make_progress_bar()
        # tqdm normalises None desc to an empty string
        assert pbar.desc == ""
        pbar.close()

    def test_total_is_set(self):
        """The total parameter is forwarded to tqdm."""
        pbar = make_progress_bar(total=42)
        assert pbar.total == 42
        pbar.close()

    def test_unit_is_set(self):
        """The unit parameter is forwarded to tqdm."""
        pbar = make_progress_bar(unit="paper")
        assert pbar.unit == "paper"
        pbar.close()

    def test_default_unit_is_item(self):
        """The default unit is 'item'."""
        pbar = make_progress_bar()
        assert pbar.unit == "item"
        pbar.close()

    def test_dynamic_ncols_is_true(self):
        """dynamic_ncols is enabled for adaptive terminal width."""
        pbar = make_progress_bar()
        # tqdm stores dynamic_ncols as a callable (screen-shape function) when enabled.
        assert pbar.dynamic_ncols is not None
        assert pbar.dynamic_ncols is not False
        pbar.close()

    def test_context_manager_usage(self):
        """make_progress_bar can be used as a context manager."""
        with make_progress_bar(desc="Test", total=3, unit="step") as pbar:
            assert isinstance(pbar, tqdm)
            pbar.update(1)
            pbar.update(2)
        # After the context exits, n should reflect the updates.
        assert pbar.n == 3

    def test_update_increments_count(self):
        """Calling update advances the internal counter."""
        pbar = make_progress_bar(total=10, unit="paper")
        pbar.update(5)
        assert pbar.n == 5
        pbar.close()

    def test_disable_suppresses_output(self):
        """When disable=True the progress bar is silenced."""
        pbar = make_progress_bar(total=10, disable=True)
        assert pbar.disable is True
        pbar.close()

    def test_disable_false_by_default(self):
        """By default the progress bar is enabled."""
        pbar = make_progress_bar(total=10)
        assert pbar.disable is False
        pbar.close()
