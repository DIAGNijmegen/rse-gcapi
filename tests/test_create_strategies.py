from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gcapi.create_strategies import (
    FileSocketValueCreateStrategy,
    ImageSocketValueCreateStrategy,
    JobInputsCreateStrategy,
    SocketValueCreateStrategy,
    TooManyFiles,
    ValueSocketValueCreateStrategy,
    clean_file_source,
)
from gcapi.models import AlgorithmInterface
from tests.factories import (
    AlgorithmFactory,
    HyperlinkedComponentInterfaceValueFactory,
    HyperlinkedImageFactory,
    SocketFactory,
)

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
def test_prep_file_source(source, maximum_number, context):
    with context:
        clean_file_source(source, maximum_number=maximum_number)


@pytest.mark.parametrize(
    "init_cls,socket,expected_cls,context",
    (
        (
            SocketValueCreateStrategy,
            SocketFactory(super_kind="Image"),
            ImageSocketValueCreateStrategy,
            nullcontext(),
        ),
        (
            SocketValueCreateStrategy,
            SocketFactory(super_kind="File"),
            FileSocketValueCreateStrategy,
            nullcontext(),
        ),
        (
            SocketValueCreateStrategy,
            SocketFactory(super_kind="Value"),
            ValueSocketValueCreateStrategy,
            nullcontext(),
        ),
        (
            SocketValueCreateStrategy,
            SocketFactory(super_kind="I do not exist"),
            None,
            pytest.raises(NotImplementedError),
        ),
        (
            ImageSocketValueCreateStrategy,
            SocketFactory(super_kind="File"),
            None,
            pytest.raises(RuntimeError),
        ),
    ),
)
def test_socket_strategy_specialization(
    init_cls, socket, expected_cls, context
):
    with context:
        strategy = init_cls(
            source=[],
            socket=socket,
            client=MagicMock(),
        )

    if expected_cls:
        assert type(strategy) is expected_cls


file_socket = SocketFactory(super_kind="File")
image_socket = SocketFactory(super_kind="Image")
value_socket = SocketFactory(super_kind="Value")


@pytest.mark.parametrize(
    "socket,source,context",
    (
        (
            file_socket,
            HyperlinkedComponentInterfaceValueFactory(),
            pytest.raises(ValueError),
        ),
        (
            image_socket,
            HyperlinkedComponentInterfaceValueFactory(),
            pytest.raises(ValueError),
        ),
        (
            value_socket,
            HyperlinkedComponentInterfaceValueFactory(),
            pytest.raises(ValueError),
        ),
        (
            file_socket,
            HyperlinkedComponentInterfaceValueFactory(
                interface=file_socket, file="foo.json"
            ),
            nullcontext(),
        ),
        (
            image_socket,
            HyperlinkedComponentInterfaceValueFactory(
                interface=image_socket, image="someurl"
            ),
            nullcontext(),
        ),
        (
            value_socket,
            HyperlinkedComponentInterfaceValueFactory(
                interface=value_socket, value="foo"
            ),
            nullcontext(),
        ),
    ),
)
def test_socket_strategy_reuse_of_sockets_prep(socket, source, context):
    strategy = SocketValueCreateStrategy(
        source=source,
        socket=socket,
        client=MagicMock(),
    )
    with context:
        strategy.prepare()


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
def test_file_socket_value_prep(source, context, interface_kind):
    strategy = FileSocketValueCreateStrategy(
        source=source,
        socket=SocketFactory(super_kind="File", kind=interface_kind),
        client=MagicMock(),
    )
    with context:
        strategy.prepare()


def test_file_socket_value_prep_socket_reuse():
    socket = SocketFactory(super_kind="File")

    strategy = FileSocketValueCreateStrategy(
        source=HyperlinkedComponentInterfaceValueFactory(
            interface=socket,
            file="https://grand-challenge.org/media/components/componentinterfacevalue/5d/57/1793367/file.json",
        ),
        socket=socket,
        client=MagicMock(),
    )

    strategy.prepare()


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
        (  # Re-use an existing image
            HyperlinkedImageFactory(),
            nullcontext(),
        ),
    ),
)
def test_image_socket_value_prep(source, context):
    strategy = ImageSocketValueCreateStrategy(
        source=source,
        socket=SocketFactory(super_kind="Image"),
        client=MagicMock(),
    )
    with context:
        strategy.prepare()


def test_image_socket_value_prep_socket_reuse():
    socket = SocketFactory(super_kind="Image")

    strategy = ImageSocketValueCreateStrategy(
        source=HyperlinkedComponentInterfaceValueFactory(
            interface=socket,
            image=HyperlinkedImageFactory().api_url,
        ),
        socket=socket,
        client=MagicMock(),
    )

    strategy.prepare()


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
def test_value_socket_value_prep(source, context):
    strategy = ValueSocketValueCreateStrategy(
        source=source,
        socket=SocketFactory(super_kind="Value"),
        client=MagicMock(),
    )
    with context:
        strategy.prepare()


def test_value_socket_value_prep_socket_reuse():
    socket = SocketFactory(super_kind="Value")

    strategy = ValueSocketValueCreateStrategy(
        source=HyperlinkedComponentInterfaceValueFactory(
            interface=socket,
            value="foo",
        ),
        socket=socket,
        client=MagicMock(),
    )

    strategy.prepare()


@pytest.mark.parametrize(
    "algorithm,inputs,context",
    (
        (  # algo socket < input socket
            AlgorithmFactory(interfaces=[]),
            {
                "foo": TESTDATA / "image10x10x101.mha",
            },
            pytest.raises(ValueError),
        ),
        (  # algo socket > input socket
            AlgorithmFactory(
                interfaces=[
                    AlgorithmInterface(
                        inputs=[
                            SocketFactory(),
                        ],
                        outputs=[],
                    )
                ]
            ),
            {},
            pytest.raises(ValueError),
        ),
        (
            # algo ci = input ci
            AlgorithmFactory(
                interfaces=[
                    AlgorithmInterface(
                        inputs=[
                            SocketFactory(slug="a-slug"),
                        ],
                        outputs=[],
                    )
                ]
            ),
            {
                "a-slug": TESTDATA / "image10x10x101.mha",
            },
            nullcontext(),
        ),
    ),
)
def test_job_inputs_create_prep(algorithm, inputs, context):
    strategy = JobInputsCreateStrategy(
        algorithm=algorithm,
        inputs=inputs,
        client=MagicMock(),
    )
    with context:
        strategy.prepare()
