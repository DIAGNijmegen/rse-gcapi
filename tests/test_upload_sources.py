from contextlib import nullcontext
from pathlib import Path

import pytest

from gcapi.upload_sources import (
    FileProtoCIV,
    ImageProtoCIV,
    TooManyFiles,
    ValueProtoCIV,
    clean_file_source,
    get_proto_civ_class,
)
from tests.factories import (
    ComponentInterfaceFactory,
    HyperlinkedImageFactory,
    SimpleImageFactory,
)

TESTDATA = Path(__file__).parent / "testdata"

from unittest.mock import MagicMock


@pytest.mark.parametrize(
    "source,max_number,context",
    (
        (
            TESTDATA / "test.json",
            None,
            nullcontext(),
        ),
        (
            [TESTDATA / "test.json"],
            None,
            nullcontext(),
        ),
        (
            str(TESTDATA / "test.json"),
            None,
            nullcontext(),
        ),
        (
            [str(TESTDATA / "test.json")],
            None,
            nullcontext(),
        ),
        (
            [TESTDATA / "test.json", TESTDATA / "test.json"],
            1,
            pytest.raises(TooManyFiles),
        ),
        (
            "I DO NOT EXIST",
            None,
            pytest.raises(FileNotFoundError),
        ),
        (
            ["I DO NOT EXIST"],
            None,
            pytest.raises(FileNotFoundError),
        ),
        (
            [],
            None,
            pytest.raises(FileNotFoundError),
        ),
    ),
)
def test_clean_file_source(source, max_number, context):
    with context:
        clean_file_source(source, max_number)


@pytest.mark.parametrize(
    "interface,cls,context",
    (
        (
            ComponentInterfaceFactory(super_kind="Image"),
            ImageProtoCIV,
            nullcontext(),
        ),
        (
            ComponentInterfaceFactory(super_kind="File"),
            FileProtoCIV,
            nullcontext(),
        ),
        (
            ComponentInterfaceFactory(super_kind="Value"),
            ValueProtoCIV,
            nullcontext(),
        ),
        (
            ComponentInterfaceFactory(super_kind="I do not exist"),
            None,
            pytest.raises(ValueError),
        ),
    ),
)
def test_proto_civ_class(interface, cls, context):
    with context:
        proto_civ_class = get_proto_civ_class(interface)

    if cls:
        assert proto_civ_class == cls


@pytest.mark.parametrize(
    "source,context",
    (
        (TESTDATA / "test.json", nullcontext()),
        (
            [TESTDATA / "test.json", TESTDATA / "test.json"],
            pytest.raises(TooManyFiles),
        ),
    ),
)
def test_file_civ_validation(source, context):
    with context:
        FileProtoCIV(
            source=source,
            interface=ComponentInterfaceFactory(super_kind="File"),
            client=MagicMock(),
        )


@pytest.mark.parametrize(
    "source,context,interface_kind",
    (
        ({"foo": "bar"}, nullcontext(), "Anything"),
        (
            "A string which is not a file",
            pytest.raises(FileNotFoundError),
            "String",
        ),
    ),
)
def test_value_on_file_civ(source, context, interface_kind):
    with context:
        FileProtoCIV(
            source=source,
            interface=ComponentInterfaceFactory(
                super_kind="File", kind=interface_kind
            ),
            client=MagicMock(),
        )


@pytest.mark.parametrize(
    "source,context",
    (
        (TESTDATA / "image10x10x101.mha", nullcontext()),
        (
            [
                TESTDATA / "image10x10x10.mhd",
                TESTDATA / "image10x10x10.zraw",
            ],
            nullcontext(),
        ),
        (SimpleImageFactory(), nullcontext()),
        (HyperlinkedImageFactory(), nullcontext()),
    ),
)
def test_image_civ_validation(source, context):
    with context:
        ImageProtoCIV(
            source=source,
            interface=ComponentInterfaceFactory(super_kind="Image"),
            client=MagicMock(),
        )


@pytest.mark.parametrize(
    "source,context",
    (
        (TESTDATA / "test.json", nullcontext()),
        ([TESTDATA / "test.json"], nullcontext()),
        (
            [
                TESTDATA / "test.json",
                TESTDATA / "test.json",
            ],
            pytest.raises(TooManyFiles),
        ),
        (TESTDATA / "invalid_test.json", pytest.raises(ValueError)),
        ({"foo": "bar"}, nullcontext()),
        (["foo", "bar"], nullcontext()),
        (1, nullcontext()),
        (None, nullcontext()),
        ([], nullcontext()),
        (object(), pytest.raises(TypeError)),
    ),
)
def test_value_civ_validation(source, context):
    with context:
        ValueProtoCIV(
            source=source,
            interface=ComponentInterfaceFactory(super_kind="Value"),
            client=MagicMock(),
        )
