import pytest

from gcapi.models import Algorithm

DEFAULT_ALGORITHM_ARGS = {
    "pk": "1234",
    "api_url": "",
    "url": "",
    "description": "",
    "title": "",
    "logo": "",
    "slug": "",
    "average_duration": 0.0,
    "inputs": [],
    "outputs": [],
}


def test_extra_definitions_allowed():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS, extra="extra")

    assert a.pk == "1234"

    with pytest.raises(AttributeError):
        a.extra


def test_getitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    assert a["pk"] == "1234"
    assert a.pk == "1234"


def test_setattribute():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    a.pk = "5678"

    assert a["pk"] == "5678"
    assert a.pk == "5678"


def test_setitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    a["pk"] = "5678"

    assert a["pk"] == "5678"
    assert a.pk == "5678"


def test_delattr():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    del a.pk

    with pytest.raises(AttributeError):
        assert a["pk"] == "5678"

    with pytest.raises(AttributeError):
        assert a.pk == "5678"


def test_delitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    del a["pk"]

    with pytest.raises(AttributeError):
        assert a["pk"] == "5678"

    with pytest.raises(AttributeError):
        assert a.pk == "5678"
