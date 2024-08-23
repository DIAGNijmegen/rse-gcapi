from contextlib import nullcontext
from pathlib import Path

import pytest

from gcapi.upload_sources import (
    FileProtoCIV,
    ImageProtoCIV,
    ProtoCIV,
    TooManyFiles,
    ValueProtoCIV,
    clean_file_source,
)
from tests.factories import (
    ComponentInterfaceFactory,
    HyperlinkedImageFactory,
    SimpleImageFactory,
)
from tests.utils import sync_generator_test

TESTDATA = Path(__file__).parent / "testdata"

from unittest.mock import MagicMock


@pytest.mark.parametrize(
    "source,maximum_number,context",
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
def test_clean_file_source(source, maximum_number, context):
    with context:
        clean_file_source(source, maximum_number=maximum_number)


@pytest.mark.parametrize(
    "init_cls,interface,cls,context",
    (
        (
            ProtoCIV,
            ComponentInterfaceFactory(super_kind="Image"),
            ImageProtoCIV,
            nullcontext(),
        ),
        (
            ProtoCIV,
            ComponentInterfaceFactory(super_kind="File"),
            FileProtoCIV,
            nullcontext(),
        ),
        (
            ProtoCIV,
            ComponentInterfaceFactory(super_kind="Value"),
            ValueProtoCIV,
            nullcontext(),
        ),
        (
            ProtoCIV,
            ComponentInterfaceFactory(super_kind="I do not exist"),
            None,
            pytest.raises(NotImplementedError),
        ),
        (
            ImageProtoCIV,
            ComponentInterfaceFactory(super_kind="File"),
            None,
            pytest.raises(RuntimeError),
        ),
    ),
)
def test_proto_civ_class(init_cls, interface, cls, context):
    with context:
        proto_civ = init_cls(
            source=[],
            interface=interface,
            client_api=MagicMock(),
        )

    if cls:
        assert type(proto_civ) is cls


@pytest.mark.parametrize(
    "source,context,interface_kind",
    (
        (
            TESTDATA / "test.json",
            nullcontext(),
            "Anything",
        ),
        (
            [TESTDATA / "test.json", TESTDATA / "test.json"],
            pytest.raises(TooManyFiles),
            "Anything",
        ),
        (  # Direct JSON on file
            {"foo": "bar"},
            nullcontext(),
            "Anything",
        ),
        (
            "A string which is not a file",
            pytest.raises(FileNotFoundError),
            "String",
        ),
    ),
)
@sync_generator_test
def test_file_civ_clean(source, context, interface_kind):
    proto_civ = FileProtoCIV(
        source=source,
        interface=ComponentInterfaceFactory(
            super_kind="File", kind=interface_kind
        ),
        client_api=MagicMock(),
    )
    with context:
        yield from proto_civ.clean()


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
@sync_generator_test
def test_image_civ_clean(source, context):
    proto_civ = ImageProtoCIV(
        source=source,
        interface=ComponentInterfaceFactory(super_kind="Image"),
        client_api=MagicMock(),
    )
    with context:
        yield from proto_civ.clean()


@pytest.mark.parametrize(
    "source,context",
    (
        (TESTDATA / "test.json", nullcontext()),
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
@sync_generator_test
def test_value_civ_clean(source, context):
    proto_civ = ValueProtoCIV(
        source=source,
        interface=ComponentInterfaceFactory(super_kind="Value"),
        client_api=MagicMock(),
    )
    with context:
        yield from proto_civ.clean()
