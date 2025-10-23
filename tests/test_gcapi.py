import pytest

from gcapi import Client
from tests.utils import ADMIN_TOKEN


@pytest.mark.parametrize(
    "kwargs", ({}, {"token": ""}, {"token": "not a token"})
)
def test_no_auth_exception(kwargs):
    with pytest.raises(RuntimeError):
        Client(**kwargs)


def test_headers():
    token = "foo"
    c = Client(token=token)
    assert c._auth_header["Authorization"] == f"BEARER {token}"
    assert c.headers["Accept"] == "application/json"


def test_token_via_env_var(monkeypatch):
    token = f"BEARER {ADMIN_TOKEN}"
    monkeypatch.setenv("GRAND_CHALLENGE_AUTHORIZATION", token)
    c = Client()
    assert c._auth_header["Authorization"] == token


def test_token_precidence(monkeypatch):
    monkeypatch.setenv("GRAND_CHALLENGE_AUTHORIZATION", "TOKEN fromenv")
    c = Client(token="fromcli")
    assert c._auth_header["Authorization"] == "BEARER fromcli"


@pytest.mark.parametrize(
    "token",
    [
        "qwerty",
        "TOKEN qwerty",
        "BEARER qwerty",
        "Bearer qwerty",
        "bearer qwerty",
        "whatever qwerty",
        "  TOKEN   qwerty    ",
    ],
)
@pytest.mark.parametrize("environ", (True, False))
def test_token_rewriting(monkeypatch, token, environ):
    if environ:
        monkeypatch.setenv("GRAND_CHALLENGE_AUTHORIZATION", token)
        kwargs = {}
    else:
        kwargs = {"token": token}

    c = Client(**kwargs)
    assert c._auth_header["Authorization"] == "BEARER qwerty"


def test_http_base_url():
    with pytest.raises(RuntimeError):
        Client(token="foo", base_url="http://example.test")


def test_custom_base_url():
    c = Client(token="foo")
    assert str(c.base_url).startswith("https://grand-challenge.org")

    c = Client(token="foo", base_url="https://example.test")
    assert str(c.base_url).startswith("https://example.test")


@pytest.mark.parametrize(
    "url",
    (
        "https://example.test/api/v1/",
        "https://example.test/",
        "https://example.test",
        "https://example.test/another/",
        "https://example.test/../../foo/",
    ),
)
def test_same_domain_calls_are_ok(url):
    c = Client(token="foo", base_url="https://example.test/api/v1/")
    assert c._validate_url(url=url) is None


@pytest.mark.parametrize(
    "url",
    (
        "https://notexample.test/api/v1/",
        "http://example.test/api/v1/",
        "https://exаmple.com/api/v1/",  # а = \u0430
        "https://sub.example.test/api/v1/",
        # This is working now because "URL" normalizes this. Expected!
        # "https://example.test:443/api/v1/",
        "example.test/api/v1/",
        "//example.test/api/v1/",
    ),
)
def test_invalid_url_fails(url):
    c = Client(token="foo", base_url="https://example.test/api/v1/")
    with pytest.raises(RuntimeError):
        c._validate_url(url=url)
