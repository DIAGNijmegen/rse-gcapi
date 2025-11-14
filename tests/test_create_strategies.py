from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest
from grand_challenge_dicom_de_identifier.exceptions import (
    RejectedDICOMFileError,
)

from gcapi.create_strategies import (
    DICOMImageSetFileCreateStrategy,
    FileCreateStrategy,
    FileFromSVCreateStrategy,
    FileJSONCreateStrategy,
    ImageCreateStrategy,
    ImageFromImageCreateStrategy,
    ImageFromSVCreateStrategy,
    JobInputsCreateStrategy,
    SocketValueSpec,
    TooManyFiles,
    ValueCreateStrategy,
    ValueFromFileCreateStrategy,
    ValueFromSVStrategy,
    clean_file_source,
    select_socket_value_strategy,
)
from gcapi.exceptions import ObjectNotFound, SocketNotFound
from gcapi.models import AlgorithmInterface
from tests import TESTDATA
from tests.factories import (
    AlgorithmFactory,
    HyperlinkedComponentInterfaceValueFactory,
    HyperlinkedImageFactory,
    SocketFactory,
)


@pytest.mark.parametrize(
    "files,maximum_number,context",
    (
        (
            [TESTDATA / "test.json"],
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
            ["I DO NOT EXIST"],
            None,
            pytest.raises(FileNotFoundError),
        ),
        (
            object(),
            None,
            pytest.raises(
                TypeError, match="files must be a list of file paths"
            ),
        ),
        (
            [],
            None,
            pytest.raises(FileNotFoundError),
        ),
    ),
)
def test_prep_file_source(files, maximum_number, context):
    with context:
        clean_file_source(files, maximum_number=maximum_number)


file_socket = SocketFactory(super_kind="File")
image_socket = SocketFactory(super_kind="Image")
dicom_image_set_socket = SocketFactory(
    super_kind="Image",
    kind="DICOM Image Set",
)
value_socket = SocketFactory(super_kind="Value")


@pytest.mark.parametrize(
    "spec, socket, context, expected_cls",
    (
        (
            SocketValueSpec(
                socket_slug=file_socket.slug,
                files=[TESTDATA / "test.json"],
            ),
            file_socket,
            nullcontext(),
            FileCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=file_socket.slug,
                file=TESTDATA / "test.json",
            ),
            file_socket,
            nullcontext(),
            FileCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=file_socket.slug,
                file=[TESTDATA / "test.json"],  # type: ignore
            ),
            file_socket,
            pytest.raises(TypeError),
            None,
        ),
        (
            SocketValueSpec(
                socket_slug=file_socket.slug,
                files=[TESTDATA / "test.json", TESTDATA / "test.json"],
            ),
            file_socket,
            pytest.raises(
                ValueError,
                match="You can only provide one file",
            ),
            None,
        ),
        (
            SocketValueSpec(socket_slug=file_socket.slug, value=42),
            file_socket,
            nullcontext(),
            FileJSONCreateStrategy,
        ),
        (  # An existing socket value
            SocketValueSpec(
                socket_slug=file_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=file_socket,
                    file="https://grand-challenge.org/media/components/componentinterfacevalue/5d/57/1793367/file.json",
                ),
            ),
            file_socket,
            nullcontext(),
            FileFromSVCreateStrategy,
        ),
        (  # An existing socket value, but not with not the same socket
            SocketValueSpec(
                socket_slug=file_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=value_socket,
                    value=42,
                ),
            ),
            file_socket,
            pytest.raises(ValueError, match="does not match socket"),
            None,
        ),
        (  # An existing socket value, with a missing file (corrupt)
            SocketValueSpec(
                socket_slug=file_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=file_socket,
                    file=None,
                ),
            ),
            file_socket,
            pytest.raises(ValueError, match="must have a file"),
            None,
        ),
        (  # An invalid socket value
            SocketValueSpec(
                socket_slug=file_socket.slug,
                existing_socket_value="I am not a socket value",  # type: ignore
            ),
            file_socket,
            pytest.raises(ValueError, match="existing_socket_value must be a"),
            None,
        ),
    ),
)
def test_file_socket_value_strategy_init(spec, socket, context, expected_cls):
    client_mock = MagicMock()

    def mock_socket_detail(slug=None, **__):
        if slug == socket.slug:
            return socket
        else:
            return SocketFactory(slug=slug)

    client_mock._fetch_socket_detail = mock_socket_detail

    with context:
        with select_socket_value_strategy(
            spec=spec, client=client_mock
        ) as strategy:
            pass
    if expected_cls:
        assert type(strategy) is expected_cls


@pytest.mark.parametrize(
    "spec, socket, context, expected_cls",
    (
        (
            SocketValueSpec(
                socket_slug=image_socket.slug,
                files=[TESTDATA / "image10x10x101.mha"],
            ),
            image_socket,
            nullcontext(),
            ImageCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=image_socket.slug,
                file=TESTDATA / "image10x10x101.mha",
            ),
            image_socket,
            nullcontext(),
            ImageCreateStrategy,
        ),
        (  # DICOM Image Set, single file
            SocketValueSpec(
                socket_slug=dicom_image_set_socket.slug,
                file=TESTDATA / "basic.dcm",
                image_name="foo",
            ),
            dicom_image_set_socket,
            nullcontext(),
            DICOMImageSetFileCreateStrategy,
        ),
        (  # DICOM Image Set, multiple files
            SocketValueSpec(
                socket_slug=dicom_image_set_socket.slug,
                files=[TESTDATA / "basic.dcm"],
                image_name="foo",
            ),
            dicom_image_set_socket,
            nullcontext(),
            DICOMImageSetFileCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=image_socket.slug,
                files=[
                    TESTDATA / "image10x10x101.mha",
                    TESTDATA / "image10x10x101.mha",
                ],
            ),
            image_socket,
            nullcontext(),
            ImageCreateStrategy,
        ),
        (  # An existing socket value
            SocketValueSpec(
                socket_slug=image_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=image_socket,
                    image="https://example.test/api/v1/cases/images/a-uuid/",
                ),
            ),
            image_socket,
            nullcontext(),
            ImageFromSVCreateStrategy,
        ),
        (  # An existing socket value (DICOM Image Set)
            SocketValueSpec(
                socket_slug=dicom_image_set_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=dicom_image_set_socket,
                    image="https://example.test/api/v1/cases/images/a-uuid/",
                ),
            ),
            dicom_image_set_socket,
            nullcontext(),
            ImageFromSVCreateStrategy,
        ),
        (  # An existing socket value, but not with the same socket kind
            SocketValueSpec(
                socket_slug=image_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=value_socket,
                    value=42,
                ),
            ),
            image_socket,
            pytest.raises(ValueError, match="does not match socket"),
            None,
        ),
        (  # Same super kind but not exactly the same
            SocketValueSpec(
                socket_slug=image_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=SocketFactory(super_kind="Image"),
                    image="https://example.test/api/v1/cases/images/a-uuid/",
                ),
            ),
            image_socket,
            pytest.raises(ValueError, match="does not match socket"),
            None,
        ),
        (  # An existing socket value, with a missing image (corrupt)
            SocketValueSpec(
                socket_slug=image_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=image_socket,
                    image=None,
                ),
            ),
            image_socket,
            pytest.raises(ValueError, match="must have an image"),
            None,
        ),
        (  # An existing socket value, with an invalid value (corrupt)
            SocketValueSpec(
                socket_slug=image_socket.slug,
                existing_socket_value=None,  # type: ignore
            ),
            image_socket,
            pytest.raises(ValueError, match="existing_socket_value must be a"),
            None,
        ),
        (  # An existing image by API URL
            SocketValueSpec(
                socket_slug=image_socket.slug,
                existing_image_api_url="https://example.test/api/v1/cases/images/a-uuid/",
            ),
            image_socket,
            nullcontext(),
            ImageFromImageCreateStrategy,
        ),
        (  # Non-existent or non-accessible image
            SocketValueSpec(
                socket_slug=image_socket.slug,
                existing_image_api_url="I do not exist or you may not access me, search not",
            ),
            image_socket,
            pytest.raises(ObjectNotFound),
            None,
        ),
        (  # Non-existent or non-accessible image (via socket value)
            SocketValueSpec(
                socket_slug=image_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=image_socket,
                    image="I do not exist or you may not access me, search not",
                ),
            ),
            image_socket,
            pytest.raises(ObjectNotFound),
            None,
        ),
        (  # DICOM Image Set, missing image name
            SocketValueSpec(
                socket_slug=dicom_image_set_socket.slug,
                file=TESTDATA / "basic.dcm",
            ),
            dicom_image_set_socket,
            pytest.raises(
                ValueError, match="you must also specify an image_name"
            ),
            None,
        ),
        (  # DICOM Image Set, unsupported DICOM file
            SocketValueSpec(
                socket_slug=dicom_image_set_socket.slug,
                file=TESTDATA / "unsupported.dcm",
                image_name="foo",
            ),
            dicom_image_set_socket,
            pytest.raises(
                RejectedDICOMFileError,
                match="Unsupported SOP Class",
            ),
            None,
        ),
        (  # Image set, but providing image_name
            SocketValueSpec(
                socket_slug=image_socket.slug,
                files=[
                    TESTDATA / "image10x10x101.mha",
                    TESTDATA / "image10x10x101.mha",
                ],
                image_name="foo",
            ),
            image_socket,
            pytest.raises(
                ValueError,
                match="image_name can only be specified when uploading a DICOM image set",
            ),
            None,
        ),
    ),
)
def test_image_socket_value_strategy_init(spec, socket, context, expected_cls):
    client_mock = MagicMock()

    def mock_socket_detail(slug=None, **__):
        if slug == socket.slug:
            return socket
        else:
            raise SocketNotFound(slug=slug)

    client_mock._fetch_socket_detail = mock_socket_detail

    def mock_images_detail(api_url=None, **__):
        if api_url == "https://example.test/api/v1/cases/images/a-uuid/":
            return HyperlinkedImageFactory()
        else:
            raise ObjectNotFound  # Also covers non accessible images

    client_mock.images.detail = mock_images_detail

    with context:
        with select_socket_value_strategy(
            spec=spec, client=client_mock
        ) as strategy:
            pass
    if expected_cls:
        assert type(strategy) is expected_cls


@pytest.mark.parametrize(
    "spec, socket, context, expected_cls",
    (
        (
            SocketValueSpec(
                socket_slug=value_socket.slug,
                files=[TESTDATA / "test.json"],
            ),
            value_socket,
            nullcontext(),
            ValueFromFileCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=value_socket.slug,
                file=TESTDATA / "test.json",
            ),
            value_socket,
            nullcontext(),
            ValueFromFileCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=value_socket.slug,
                files=[TESTDATA / "test.json", TESTDATA / "test.json"],
            ),
            value_socket,
            pytest.raises(ValueError, match="You can only provide one file"),
            None,
        ),
        (
            SocketValueSpec(
                socket_slug=value_socket.slug,
                value=42,
            ),
            value_socket,
            nullcontext(),
            ValueCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=value_socket.slug,
                value="String",
            ),
            value_socket,
            nullcontext(),
            ValueCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=value_socket.slug,
                value=["String"],
            ),
            value_socket,
            nullcontext(),
            ValueCreateStrategy,
        ),
        (
            SocketValueSpec(
                socket_slug=value_socket.slug,
                value=object(),  # Not JSON serializable
            ),
            value_socket,
            pytest.raises(ValueError, match="is not JSON serializable"),
            None,
        ),
        (
            SocketValueSpec(
                socket_slug=value_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=value_socket,
                    value=42,
                ),
            ),
            value_socket,
            nullcontext(),
            ValueFromSVStrategy,
        ),
        (  # Different socket
            SocketValueSpec(
                socket_slug=value_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=SocketFactory(super_kind="Value"),
                    value=42,
                ),
            ),
            value_socket,
            pytest.raises(ValueError, match="does not match socket"),
            None,
        ),
        (  # Corrupt - missing value
            SocketValueSpec(
                socket_slug=value_socket.slug,
                existing_socket_value=HyperlinkedComponentInterfaceValueFactory(
                    interface=value_socket,
                    value=None,
                ),
            ),
            value_socket,
            pytest.raises(ValueError, match="must have a value"),
            None,
        ),
        (  # Corrupt - missing value
            SocketValueSpec(
                socket_slug=value_socket.slug,
                existing_socket_value="Not a socket value",  # type: ignore
            ),
            value_socket,
            pytest.raises(ValueError, match="existing_socket_value must be a"),
            None,
        ),
    ),
)
def test_value_socket_value_strategy_init(spec, socket, context, expected_cls):
    client_mock = MagicMock()

    def mock_socket_detail(slug=None, **__):
        if slug == socket.slug:
            return socket
        else:
            return SocketFactory(slug=slug)

    client_mock._fetch_socket_detail = mock_socket_detail

    with context:
        with select_socket_value_strategy(
            spec=spec, client=client_mock
        ) as strategy:
            pass

    if expected_cls:
        assert type(strategy) is expected_cls


@pytest.mark.parametrize(
    "algorithm,inputs,context",
    (
        (  # algo socket < input socket
            AlgorithmFactory(interfaces=[]),
            [
                SocketValueSpec(
                    socket_slug="foo",
                    files=[TESTDATA / "image10x10x101.mha"],
                )
            ],
            pytest.raises(
                ValueError, match="No matching interface for sockets"
            ),
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
            [],
            pytest.raises(
                ValueError, match="No matching interface for sockets"
            ),
        ),
        (
            # algo ci = input ci
            AlgorithmFactory(
                interfaces=[
                    AlgorithmInterface(
                        inputs=[
                            file_socket,
                        ],
                        outputs=[],
                    )
                ]
            ),
            [
                SocketValueSpec(
                    socket_slug=file_socket.slug,
                    files=[TESTDATA / "image10x10x101.mha"],
                )
            ],
            nullcontext(),
        ),
    ),
)
def test_job_inputs_create_prep(algorithm, inputs, context):
    client_mock = MagicMock()

    client_mock._fetch_socket_detail = MagicMock(return_value=file_socket)

    with context:
        with JobInputsCreateStrategy(
            algorithm=algorithm,
            inputs=inputs,
            client=client_mock,
        ):
            pass


@pytest.mark.parametrize(
    "spec_dict,context",
    (
        # Valid cases - exactly one value source
        (
            {"socket_slug": "test-socket", "value": 42},
            nullcontext(),
        ),
        (  # Value can be set to None
            {"socket_slug": "test-socket", "value": None},
            nullcontext(),
        ),
        (
            {"socket_slug": "test-socket", "files": [TESTDATA / "test.json"]},
            nullcontext(),
        ),
        (
            {
                "socket_slug": "test-socket",
                "files": [TESTDATA / "test.json"],
                "image_name": "a_image_name",
            },
            nullcontext(),
        ),
        (
            {
                "socket_slug": "test-socket",
                "existing_image_api_url": "https://example.com/api/v1/images/123/",
            },
            nullcontext(),
        ),
        (
            {
                "socket_slug": "test-socket",
                "existing_socket_value": HyperlinkedComponentInterfaceValueFactory(),
            },
            nullcontext(),
        ),
        # Invalid cases - multiple value sources
        (
            {"socket_slug": "test-socket", "value": 42, "files": []},
            pytest.raises(
                ValueError, match="Only one source can be specified"
            ),
        ),
        (
            {
                "socket_slug": "test-socket",
                "value": 42,
                "existing_image_api_url": "https://example.com/api/v1/images/123/",
            },
            pytest.raises(
                ValueError, match="Only one source can be specified"
            ),
        ),
        (
            {
                "socket_slug": "test-socket",
                "value": 42,
                "files": [],
                "existing_image_api_url": "https://example.test/api/v1/images/123/",
            },
            pytest.raises(
                ValueError, match="Only one source can be specified"
            ),
        ),
        (
            {
                "socket_slug": "test-socket",
                "files": [],
                "existing_image_api_url": "https://example.test/api/v1/images/123/",
                "existing_socket_value": HyperlinkedComponentInterfaceValueFactory(),
            },
            pytest.raises(
                ValueError, match="Only one source can be specified"
            ),
        ),
        # Invalid case - no value sources
        (
            {"socket_slug": "test-socket"},
            pytest.raises(
                ValueError, match="At least one source must be specified"
            ),
        ),
    ),
)
def test_socket_value_spec_validation(spec_dict, context):
    with context:
        SocketValueSpec(**spec_dict)


def test_dicom_image_set_file_create_strategy_closes_spools():
    spec = SocketValueSpec(
        socket_slug="dicom-image-set-socket",
        files=[
            TESTDATA / "basic.dcm",
            TESTDATA / "basic.dcm",
        ],
        image_name="foo",
    )
    socket = SocketFactory(
        slug="dicom-image-set-socket",
        super_kind="Image",
        kind="DICOM Image Set",
    )

    client_mock = MagicMock()

    def mock_socket_detail(slug=None, **__):
        if slug == socket.slug:
            return socket
        else:
            raise SocketNotFound(slug=slug)

    client_mock._fetch_socket_detail = mock_socket_detail

    with select_socket_value_strategy(
        spec=spec, client=client_mock
    ) as strategy:
        # A few sanity checks. Note: we do NOT call the strategy: exit it in
        # a half state
        assert isinstance(strategy, DICOMImageSetFileCreateStrategy), "Sanity"
        for f in strategy.content:
            assert not f.closed

    # After exiting the context, the spools should be closed
    for f in strategy.content:
        assert f.closed
