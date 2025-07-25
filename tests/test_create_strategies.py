from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import gcapi.create_strategies
from gcapi.create_strategies import (
    FileCreateStrategy,
    FileFromSVCreateStrategy,
    FileJSONCreateStrategy,
    ImageCreateStrategy,
    ImageFromSVCreateStrategy,
    JobInputsCreateStrategy,
    NotSupportedError,
    SocketValueCreateStrategy,
    TooManyFiles,
    ValueCreateStrategy,
    ValueFromFileCreateStrategy,
    ValueFromSVStrategy,
    _strategy_registry,
    clean_file_source,
    select_socket_value_strategy,
)
from gcapi.exceptions import ObjectNotFound
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


def test_supported_socket_value_create_strategies():
    class TestStrategy(SocketValueCreateStrategy):
        supported_super_kind = "Test"

    TestStrategy(socket=SocketFactory(super_kind="Test"), client=MagicMock())

    with pytest.raises(NotSupportedError):
        TestStrategy(
            socket=SocketFactory(super_kind="Not Test"), client=MagicMock()
        )


file_socket = SocketFactory(super_kind="File")
image_socket = SocketFactory(super_kind="Image")
value_socket = SocketFactory(super_kind="Value")


@pytest.mark.parametrize(
    "source, socket, context, expected_cls",
    (
        (
            TESTDATA / "test.json",
            file_socket,
            nullcontext(),
            FileCreateStrategy,
        ),
        (
            [TESTDATA / "test.json", TESTDATA / "test.json"],
            file_socket,
            pytest.raises(ValueError),
            None,
        ),
        (
            42,
            file_socket,
            nullcontext(),
            FileJSONCreateStrategy,
        ),
        (  # A string could easily be a misspelled file-path: so we don't allow it
            "A string which is not a file, yet it could be a misspelled file path",
            SocketFactory(super_kind="File", kind="String"),
            pytest.raises(ValueError),
            None,
        ),
        (  # An existing socket value
            HyperlinkedComponentInterfaceValueFactory(
                interface=file_socket,
                file="https://grand-challenge.org/media/components/componentinterfacevalue/5d/57/1793367/file.json",
            ),
            file_socket,
            nullcontext(),
            FileFromSVCreateStrategy,
        ),
        (  # An existing socket value, but not with not the same socket
            HyperlinkedComponentInterfaceValueFactory(
                interface=file_socket,
                file="https://grand-challenge.org/media/components/componentinterfacevalue/5d/57/1793367/file.json",
            ),
            SocketFactory(super_kind="file"),
            pytest.raises(ValueError),
            None,
        ),
        (  # An existing socket value, with a missing file (corrupt)
            HyperlinkedComponentInterfaceValueFactory(
                interface=file_socket,
                file=None,
            ),
            file_socket,
            pytest.raises(ValueError),
            None,
        ),
    ),
)
def test_file_socket_value_strategy_init(
    source, socket, context, expected_cls
):
    with context:
        strategy = select_socket_value_strategy(
            source=source,
            socket=socket,
            client=MagicMock(),
        )
    if expected_cls:
        assert type(strategy) is expected_cls


@pytest.mark.parametrize(
    "source, socket, context, expected_cls",
    (
        (
            TESTDATA / "image10x10x101.mha",
            image_socket,
            nullcontext(),
            ImageCreateStrategy,
        ),
        (
            [TESTDATA / "image10x10x101.mha", TESTDATA / "image10x10x101.mha"],
            image_socket,
            nullcontext(),
            ImageCreateStrategy,
        ),
        (
            [TESTDATA / "image10x10x101.mha", TESTDATA / "image10x10x101.mha"],
            image_socket,
            nullcontext(),
            ImageCreateStrategy,
        ),
        (
            HyperlinkedImageFactory(),
            image_socket,
            nullcontext(),
            ImageFromSVCreateStrategy,
        ),
        (
            HyperlinkedComponentInterfaceValueFactory(
                interface=image_socket,
                image="https://example.test/api/v1/cases/images/a-uuid/",
            ),
            image_socket,
            nullcontext(),
            ImageFromSVCreateStrategy,
        ),
        (
            # An existing socket value, but not with not the same socket kind
            HyperlinkedComponentInterfaceValueFactory(
                interface=file_socket,
                image="https://example.test/api/v1/cases/images/a-uuid/",
            ),
            image_socket,
            pytest.raises(ValueError),
            None,
        ),
        (
            # Same super kind but not exactly the same
            HyperlinkedComponentInterfaceValueFactory(
                interface=SocketFactory(super_kind="Image"),
                image="https://example.test/api/v1/cases/images/a-uuid/",
            ),
            image_socket,
            pytest.raises(ValueError),
            None,
        ),
        (
            # Corrupt
            HyperlinkedComponentInterfaceValueFactory(
                interface=image_socket,
                image=None,
            ),
            image_socket,
            pytest.raises(ValueError),
            None,
        ),
        (
            "a-uuid",
            image_socket,
            nullcontext(),
            ImageFromSVCreateStrategy,
        ),
        (
            "https://example.test/api/v1/cases/images/a-uuid/",
            image_socket,
            nullcontext(),
            ImageFromSVCreateStrategy,
        ),
        (
            "I do not exist, search not",
            image_socket,
            pytest.raises(ValueError),
            None,
        ),
    ),
)
def test_image_socket_value_strategy_init(
    source, socket, context, expected_cls
):
    client_mock = MagicMock()

    def mock_images_detail(pk=None, api_url=None, **__):
        if (
            pk == "a-uuid"
            or api_url == "https://example.test/api/v1/cases/images/a-uuid/"
        ):
            return HyperlinkedImageFactory()
        else:
            raise ObjectNotFound

    client_mock.images.detail = mock_images_detail

    with context:
        strategy = select_socket_value_strategy(
            source=source,
            socket=socket,
            client=client_mock,
        )
    if expected_cls:
        assert type(strategy) is expected_cls


@pytest.mark.parametrize(
    "source, socket, context, expected_cls",
    (
        (
            TESTDATA / "test.json",
            value_socket,
            nullcontext(),
            ValueFromFileCreateStrategy,
        ),
        (
            [TESTDATA / "test.json", TESTDATA / "test.json"],
            value_socket,
            pytest.raises(ValueError),
            None,
        ),
        (
            42,
            value_socket,
            nullcontext(),
            ValueCreateStrategy,
        ),
        (
            "String",
            value_socket,
            nullcontext(),
            ValueCreateStrategy,
        ),
        (
            ["String"],
            value_socket,
            nullcontext(),
            ValueCreateStrategy,
        ),
        (
            object(),  # Not JSON serializable
            value_socket,
            pytest.raises(ValueError),
            None,
        ),
        (
            HyperlinkedComponentInterfaceValueFactory(
                interface=value_socket,
                value=42,
            ),
            value_socket,
            nullcontext(),
            ValueFromSVStrategy,
        ),
        (  # Different socket
            HyperlinkedComponentInterfaceValueFactory(
                interface=SocketFactory(super_kind="Value"),
                value=42,
            ),
            value_socket,
            pytest.raises(ValueError),
            None,
        ),
        (  # Corrupt
            HyperlinkedComponentInterfaceValueFactory(
                interface=value_socket,
            ),
            value_socket,
            pytest.raises(ValueError),
            None,
        ),
    ),
)
def test_value_socket_value_strategy_init(
    source, socket, context, expected_cls
):
    with context:
        strategy = select_socket_value_strategy(
            source=source,
            socket=socket,
            client=MagicMock(),
        )
    if expected_cls:
        assert type(strategy) is expected_cls


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
    with context:
        JobInputsCreateStrategy(
            algorithm=algorithm,
            inputs=inputs,
            client=MagicMock(),
        )


def test_ordering_strategy_registry():
    """Ensure that the strategy registry is ordered correctly."""

    assert _strategy_registry == [
        # File
        gcapi.create_strategies.FileCreateStrategy,
        gcapi.create_strategies.FileJSONCreateStrategy,
        gcapi.create_strategies.FileFromSVCreateStrategy,
        # Image
        gcapi.create_strategies.ImageCreateStrategy,
        gcapi.create_strategies.ImageFromSVCreateStrategy,
        # Value
        gcapi.create_strategies.ValueFromFileCreateStrategy,
        gcapi.create_strategies.ValueFromSVStrategy,
        gcapi.create_strategies.ValueCreateStrategy,
    ]
