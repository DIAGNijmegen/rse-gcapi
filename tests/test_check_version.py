import warnings
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from gcapi import Client
from gcapi.check_version import UnsupportedVersionError, check_version


@pytest.fixture
def mock_get_version():
    with patch("gcapi.check_version.get_version") as mock:
        yield mock


@pytest.fixture
def mock_httpx_client():
    with patch("gcapi.check_version.httpx.Client") as mock:
        yield mock


@pytest.mark.parametrize(
    "current,latest,lowest,should_warn,expected_context",
    [
        # Normal operations
        ("1.0.0", "1.0.0", "0.0.0", False, nullcontext()),
        # Newer versions
        ("1.0.0", "1.0.1", "0.0.0", True, nullcontext()),
        ("1.0.0", "1.1.0", "0.0.0", True, nullcontext()),
        ("1.0.0", "2.0.0", "0.0.0", True, nullcontext()),
        ("1.0.1", "1.0.0", "0.0.0", False, nullcontext()),
        ("1.1.0", "1.0.0", "0.0.0", False, nullcontext()),
        ("2.0.0", "1.0.0", "0.0.0", False, nullcontext()),
        # Lower supported versions
        (
            "1.0.0",
            "0.0.0",
            "2.0.0",
            False,
            pytest.raises(UnsupportedVersionError),
        ),
        (
            "1.0.0",
            "3.0.0",  # Even if there is a newer version: error out
            "2.0.0",
            False,
            pytest.raises(UnsupportedVersionError),
        ),
    ],
)
def test_check_version_comparisons(
    mock_get_version,
    mock_httpx_client,
    current,
    latest,
    lowest,
    should_warn,
    expected_context,
):
    mock_get_version.return_value = current
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "latest_version": latest,
        "lowest_supported_version": lowest,
    }
    mock_httpx_client.return_value.__enter__.return_value.get.return_value = (
        mock_response
    )

    with warnings.catch_warnings(record=True) as w:
        with expected_context:
            check_version(base_url="https://example.test/")

    if should_warn:
        assert (
            len(w) == 1
        ), f"A warning should be issued for version {current} < {latest}"
        assert f"You are using gcapi version {current}" in str(w[0].message)
    else:
        assert (
            len(w) == 0
        ), f"No warning should be issued for version {current} >= {latest}"


def test_check_version_calling(mock_check_version):
    mock_check_version.assert_not_called()  # Sanity
    Client(token="Foo")
    mock_check_version.assert_called_once()
