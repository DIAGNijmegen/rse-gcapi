import warnings
from unittest.mock import MagicMock, patch

import httpx
import pytest

from gcapi import check_version


@pytest.fixture
def mock_get_version():
    with patch("gcapi.check_version.get_version") as mock:
        yield mock


@pytest.fixture
def mock_httpx_client():
    with patch("gcapi.check_version.httpx.Client") as mock:
        yield mock


@pytest.mark.parametrize(
    "current,latest,should_warn",
    [
        ("1.0.0", "1.0.1", True),
        ("1.0.0", "1.1.0", True),
        ("1.0.0", "2.0.0", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.1", "1.0.0", False),
        ("1.1.0", "1.0.0", False),
        ("2.0.0", "1.0.0", False),
    ],
)
def test_check_version_comparisons(
    mock_get_version, mock_httpx_client, current, latest, should_warn
):
    mock_get_version.return_value = current
    mock_response = MagicMock()
    mock_response.json.return_value = {"info": {"version": latest}}
    mock_httpx_client.return_value.__enter__.return_value.get.return_value = (
        mock_response
    )

    with warnings.catch_warnings(record=True) as w:
        check_version()

    if should_warn:
        assert (
            len(w) == 1
        ), f"A warning should be issued for version {current} < {latest}"
        assert f"You are using gcapi version {current}" in str(w[0].message)
    else:
        assert (
            len(w) == 0
        ), f"No warning should be issued for version {current} >= {latest}"


def test_check_version_network_error(mock_httpx_client):
    mock_httpx_client.return_value.__enter__.return_value.get.side_effect = (
        httpx.RequestError("Network error")
    )

    with warnings.catch_warnings(record=True) as w:
        check_version()

    assert len(w) == 0, "No warning should be issued for network errors"
