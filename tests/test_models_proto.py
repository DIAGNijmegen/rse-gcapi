from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gcapi.models_proto import (
    FileProtoCIV,
    ImageProtoCIV,
    ProtoCIV,
    ProtoJob,
    TooManyFiles,
    ValueProtoCIV,
    clean_file_source,
)
from tests.factories import (
    AlgorithmFactory,
    ComponentInterfaceFactory,
    HyperlinkedComponentInterfaceValueFactory,
    HyperlinkedImageFactory,
)
from tests.utils import sync_generator_test

TESTDATA = Path(__file__).parent / "testdata"


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
    "init_cls,interface,expected_cls,context",
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
def test_proto_civ_typing(init_cls, interface, expected_cls, context):
    with context:
        proto_civ = init_cls(
            source=[],
            interface=interface,
            client_api=MagicMock(),
        )

    if expected_cls:
        assert type(proto_civ) is expected_cls


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
        (  # Direct JSON value on file super_kind
            {"foo": "bar"},
            nullcontext(),
            "Anything",
        ),
        (  # Dangerously easy to overlook, so we don't allow it
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
        (  # Re-use an image
            HyperlinkedImageFactory(),
            nullcontext(),
        ),
        (  # Re-use a CIV
            HyperlinkedComponentInterfaceValueFactory(
                image=HyperlinkedImageFactory().api_url
            ),
            nullcontext(),
        ),
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
        (
            TESTDATA / "invalid_test.json",
            pytest.raises(ValueError),
        ),
        (
            {"foo": "bar"},
            nullcontext(),
        ),
        (
            ["foo", "bar"],
            nullcontext(),
        ),
        (
            1,
            nullcontext(),
        ),
        (
            None,
            nullcontext(),
        ),
        (
            [],
            nullcontext(),
        ),
        (
            object(),  # Can't dump this with JSON
            pytest.raises(TypeError),
        ),
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


@pytest.mark.parametrize(
    "algorithm,inputs,context",
    (
        (  # algo ci < input ci
            AlgorithmFactory(inputs=[]),
            {
                "foo": TESTDATA / "image10x10x101.mha",
            },
            pytest.raises(ValueError),
        ),
        (  # algo ci > input ci
            AlgorithmFactory(
                inputs=[
                    ComponentInterfaceFactory(),
                ]
            ),
            {},
            pytest.raises(ValueError),
        ),
        (  # algo ci > input ci, but default
            AlgorithmFactory(
                inputs=[
                    ComponentInterfaceFactory(default_value="bar"),
                ]
            ),
            {},
            nullcontext(),
        ),
        (  # algo ci = input ci
            AlgorithmFactory(
                inputs=[
                    ComponentInterfaceFactory(slug="a-slug"),
                ]
            ),
            {
                "a-slug": TESTDATA / "image10x10x101.mha",
            },
            nullcontext(),
        ),
    ),
)
@sync_generator_test
def test_proto_job_clean(algorithm, inputs, context):
    job = ProtoJob(
        algorithm=algorithm,
        inputs=inputs,
        client_api=MagicMock(),
    )
    with context:
        yield from job.clean()
