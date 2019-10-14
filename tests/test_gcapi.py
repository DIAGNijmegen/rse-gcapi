#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `gcapi` package."""
import sys
import os
import pytest

from click.testing import CliRunner
from requests.exceptions import HTTPError

from gcapi import Client
from gcapi import cli


def test_no_auth_exception():
    with pytest.raises(RuntimeError):
        Client()


def test_headers():
    token = "foo"
    c = Client(token=token)
    assert c.headers["Authorization"] == "TOKEN {}".format(token)
    assert c.headers["Accept"] == "application/json"


def test_http_base_url():
    with pytest.raises(RuntimeError):
        Client(token="foo", base_url="http://example.com")


def test_custom_base_url():
    c = Client(token="foo")
    assert c._base_url.startswith("https://grand-challenge.org")

    c = Client(token="foo", base_url="https://example.com")
    assert c._base_url.startswith("https://example.com")


def test_command_line_interface():
    """Test the CLI."""
    runner = CliRunner()
    result = runner.invoke(cli.main)
    assert result.exit_code == 0
    assert "gcapi.cli.main" in result.output
    help_result = runner.invoke(cli.main, ["--help"])
    assert help_result.exit_code == 0
    assert "--help  Show this message and exit." in help_result.output


@pytest.mark.skipif(sys.version_info >= (3, 0), reason="Testing a bug in Py2")
def test_mixed_string_and_unicode():
    c = Client(token="whatever")
    with pytest.raises(HTTPError):
        # The call should get here after calling urljoin
        c(path=unicode("dsfa"))


def test_chunked_uploads():
    c = Client(token="whatever")
    with pytest.raises(HTTPError):
        c.chunked_uploads.send(
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "testdata", "rnddata"
            )
        )


def test_local_response():
    c = Client(
        base_url="https://gc.localhost/api/v1/",
        verify=False,
        token="1b9436200001f2eaf57cd77db075cbb60a49a00a",
    )
    assert c.algorithms.page()
