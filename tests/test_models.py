from typing import Any

import pytest

from gcapi.models import Algorithm

DEFAULT_ALGORITHM_ARGS: dict[str, Any] = {
    "pk": "1234",
    "api_url": "",
    "url": "",
    "description": "",
    "title": "",
    "logo": "",
    "slug": "",
    "average_duration": 0.0,
    "interfaces": [],
}


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_extra_definitions_allowed():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS, extra="extra")  # type: ignore

    assert a.pk == "1234"

    with pytest.raises(AttributeError):
        a.extra  # type: ignore


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_getitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    assert a["pk"] == "1234"
    assert a.pk == "1234"


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_setattribute():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    a.pk = "5678"

    assert a["pk"] == "5678"
    assert a.pk == "5678"


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_setitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    a["pk"] = "5678"

    assert a["pk"] == "5678"
    assert a.pk == "5678"


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_delattr():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    del a.pk

    with pytest.raises(AttributeError):
        assert a["pk"] == "5678"

    with pytest.raises(AttributeError):
        assert a.pk == "5678"


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_delitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    del a["pk"]

    with pytest.raises(AttributeError):
        assert a["pk"] == "5678"

    with pytest.raises(AttributeError):
        assert a.pk == "5678"


def test_deprecation_warning_for_getitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    with pytest.warns(DeprecationWarning) as checker:
        _ = a["pk"]

    assert 'Using ["pk"] for getting attributes is deprecated' in str(
        checker.list[0].message
    )


def test_deprecation_warning_for_setitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    with pytest.warns(DeprecationWarning) as checker:
        a["pk"] = "5678"

    assert 'Using ["pk"] for setting attributes is deprecated' in str(
        checker.list[0].message
    )


def test_deprecation_warning_for_delitem():
    a = Algorithm(**DEFAULT_ALGORITHM_ARGS)

    with pytest.warns(DeprecationWarning) as checker:
        del a["pk"]

    assert 'Using ["pk"] for deleting attributes is deprecated' in str(
        checker.list[0].message
    )
