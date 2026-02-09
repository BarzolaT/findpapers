"""Pytest configuration and shared fixtures for tests."""

import pytest


@pytest.fixture
def sample_query_string():
    """Return a simple query string for testing."""
    return "[machine learning] AND [deep learning]"


@pytest.fixture
def complex_query_string():
    """Return a complex query string for testing."""
    return "[happiness] AND ([joy] OR [peace of mind]) AND NOT [stressful]"
