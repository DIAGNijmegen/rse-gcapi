from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Any

import httpx

from gcapi.typing import Unset, UnsetType

if TYPE_CHECKING:
    from gcapi.client import Client

from grand_challenge_dicom_de_identifier.deidentifier import DicomDeidentifier

from gcapi.models import (
    Algorithm,
    ComponentInterface,
    ComponentInterfaceValuePostRequest,
    HyperlinkedComponentInterfaceValue,
)


class TooManyFiles(ValueError):
    pass


@dataclass
class SocketValueSpec:
    """
    Specification for a socket value which provides exactly one source
    that will be used to create a socket value.

    Socket values are the items that constitute cases in job inputs, archive items,
    and display sets.

    Example:
        ```python
        from gcapi import SocketValueSpec

        # Directly from a value
        SocketValueSpec(socket_slug="my_value_socket", value=42)

        # Indirectly from a file
        SocketValueSpec(socket_slug="my_value_socket", file="/path/to/number.json")

        # Directly from a file
        SocketValueSpec(socket_slug="my_pdf_socket", file="/path/to/report.pdf")

        # Directly from multiple files
        SocketValueSpec(socket_slug="my_image_socket", files=["1.dcm", "2.dcm"])

        # Indirectly from an existing image
        SocketValueSpec(
            socket_slug="my_image_socket",
            existing_image_api_url="https://grand-challenge.org/api/v1/images/123/"
        )

        # Indirectly from an existing socket value
        display_set = client.display_sets.detail(pk="...")
        SocketValueSpec(
            socket_slug="my_value_socket",
            existing_socket_value=display_set.values[0]
        )

        # A DICOM Image set, including image_name
        display_set = client.display_sets.detail(pk="...")
        SocketValueSpec(
            socket_slug="my_value_socket",
            files=["/path/to/dicom/files/1.dcm", "/path/to/dicom/files/2.dcm"],
            image_name="My Image Name",
        )
        ```

    Args:
        socket_slug: The slug of the socket (required)

        value: Direct source value to set (can be None)
        file: Single source file path for file/image upload
            (e.g. `file="annotation.json"`)
        files: List of source file paths that constitute a single value/image
            (e.g. `files=["1.dcm", "2.dcm", "3.dcm"]`)
        image_name: Name for the image when uploading a DICOM image

        existing_image_api_url: An API URL of an existing image to reuse
        existing_socket_value: Existing socket value that can be reused
    """

    socket_slug: str

    value: Any = Unset
    file: str | Path | UnsetType = Unset
    files: list[str | Path] | UnsetType = Unset
    image_name: str | UnsetType = Unset

    existing_image_api_url: str | UnsetType = Unset
    existing_socket_value: HyperlinkedComponentInterfaceValue | UnsetType = (
        Unset
    )

    def __post_init__(self):

        # Wrap file
        if not isinstance(self.file, UnsetType):
            self.files = [self.file]
            del self.file

        self.validate()

    def validate(self) -> None:
        """Validate the spec without a socket context."""
        if not isinstance(self.socket_slug, str):
            raise TypeError("socket_slug must be a string")

        sources = []

        for field_name, field_value in self.__dict__.items():
            if field_name in ("socket_slug", "image_name"):
                continue
            if field_value is not Unset:
                sources.append(field_name)

        potential_source_fields = sorted(
            set(self.__dict__.keys()).difference({"socket_slug", "image_name"})
        )

        if len(sources) > 1:
            raise ValueError(
                f"Only one source can be specified, but got: {', '.join(sources)}. "
                f"Please specify only one of the available source fields ({', '.join(potential_source_fields)})."
            )

        if len(sources) == 0:
            raise ValueError(
                "At least one source must be specified. "
                "Please provide one of the available source fields ({', '.join(potential_source_fields)})."
            )

    def validate_against_socket(self, socket: ComponentInterface) -> None:
        """Validate the spec with the socket context."""
        if socket.slug != self.socket_slug:
            raise ValueError(
                f"Socket slug {self.socket_slug!r} does not match "
                f"the provided socket {socket.slug!r}"
            )

        self._validate_image_name_field(socket=socket)
        self._validated_existing_socket_value_field(socket=socket)

    def _validate_image_name_field(self, socket: ComponentInterface) -> None:
        if socket.kind.casefold() == "dicom image set":
            if all(
                [
                    self.image_name is Unset,
                    self.existing_socket_value is Unset,
                    self.existing_image_api_url is Unset,
                ]
            ):
                raise ValueError(
                    "When uploading a DICOM image set, "
                    "you must also specify an image_name."
                )
        elif self.image_name is not Unset:
            raise ValueError(
                "image_name can only be specified when "
                "uploading a DICOM image set."
            )

    def _validated_existing_socket_value_field(
        self,
        socket: ComponentInterface,
    ) -> None:
        if self.existing_socket_value is Unset:
            return

        socket_value = self.existing_socket_value
        if not isinstance(
            socket_value,
            HyperlinkedComponentInterfaceValue,
        ):
            raise ValueError(
                f"existing_socket_value must be a {HyperlinkedComponentInterfaceValue.__name__}"
            )

        if socket_value.interface.pk != socket.pk:
            raise ValueError(
                f"Source {socket_value.interface.title!r} does not "
                f"match socket {socket.slug!r}"
            )

    def __repr__(self) -> str:
        set_fields = []
        for field_name, field_value in self.__dict__.items():
            if field_name == "socket_slug":
                continue
            if field_value is not Unset:
                set_fields.append(field_name)

        parts = [f"socket_slug={self.socket_slug!r}"]
        for field_name in set_fields:
            field_value = getattr(self, field_name)
            parts.append(f"{field_name}={field_value!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


def clean_file_source(
    files: list[Path | str], *, maximum_number: int | None = None
) -> list[Path]:
    if not isinstance(files, list):
        raise TypeError("files must be a list of file paths")

    # Ensure no more than can be handled
    if maximum_number is not None and len(files) > maximum_number:
        raise TooManyFiles(
            f"The maximum is {maximum_number}, "
            f"you provided {maximum_number}: {files}"
        )

    # Ensure items exist
    cleaned = []
    for p in [Path(f) for f in files]:
        if p.exists():
            cleaned.append(p)
        else:
            raise FileNotFoundError(p)
    if not cleaned:
        raise FileNotFoundError("No files provided")

    return cleaned


class BaseCreateStrategy:
    """
    Base class that describes strategies when creating items on Grand Challenge.

    Some items can directly be created via an api call. However, some need
    a chain of dependent items to exists. The raison d'être of the strategies
    is to re-use code that checks and handles these relations.

    Each strategy prepares when initiating to support batch preparing
    before things actually land on Grand Challenge. Preparing should **not**
    create anything on Grand Challenge. But can reach out to the API.

    Calling the strategy will, if applicable, upload contents and hence cause
    objects to be created on Grand Challenge.

    If for some reason, the strategy is aborted halfway, the `close` method
    can be called to clean up any resources held by the strategy.
    """

    client: Client

    def __init__(self, *, client):
        self.client = client

    def __call__(self) -> Any: ...

    def __enter__(self):
        return self

    def __exit__(self, *_, **__):
        self.close()

    def close(self) -> None:
        """Close any resources held by the strategy."""
        pass


class SocketValueCreateStrategy(BaseCreateStrategy):
    def __init__(
        self,
        *,
        socket: ComponentInterface,
        client: Client,
    ) -> None:
        super().__init__(client=client)

        self.socket = socket

    def __call__(
        self: SocketValueCreateStrategy,
    ) -> ComponentInterfaceValuePostRequest:

        return ComponentInterfaceValuePostRequest(
            interface=self.socket.slug,
            value=None,
            file=None,
            image=None,
            upload_session=None,
            user_upload=None,
            user_uploads=None,
            image_name=None,
        )


def select_socket_value_strategy(  # noqa: C901
    *,
    spec: SocketValueSpec,
    client: Client,
) -> SocketValueCreateStrategy:

    socket = client._fetch_socket_detail(spec.socket_slug)
    kwargs = dict(
        socket=socket,
        client=client,
    )

    spec.validate_against_socket(socket=socket)

    if socket.super_kind.casefold() == "file":
        if not isinstance(spec.files, UnsetType):
            return FileCreateStrategy(
                files=spec.files,
                **kwargs,
            )
        elif not isinstance(spec.value, UnsetType):
            return FileJSONCreateStrategy(
                value=spec.value,
                **kwargs,
            )
        elif not isinstance(spec.existing_socket_value, UnsetType):
            return FileFromSVCreateStrategy(
                socket_value=spec.existing_socket_value,
                **kwargs,
            )
    elif socket.super_kind.casefold() == "image":
        if not isinstance(spec.files, UnsetType):
            if socket.kind.casefold() == "dicom image set" and not isinstance(
                spec.image_name, UnsetType
            ):
                return DICOMImageSetFileCreateStrategy(
                    files=spec.files,
                    image_name=spec.image_name,
                    **kwargs,
                )
            else:
                return ImageCreateStrategy(
                    files=spec.files,
                    **kwargs,
                )
        elif not isinstance(spec.existing_image_api_url, UnsetType):
            return ImageFromImageCreateStrategy(
                existing_image_api_url=spec.existing_image_api_url,
                **kwargs,
            )
        elif not isinstance(spec.existing_socket_value, UnsetType):
            return ImageFromSVCreateStrategy(
                existing_socket_value=spec.existing_socket_value,
                **kwargs,
            )
    elif socket.super_kind.casefold() == "value":
        if not isinstance(spec.files, UnsetType):
            return ValueFromFileCreateStrategy(
                files=spec.files,
                **kwargs,
            )
        elif not isinstance(spec.existing_socket_value, UnsetType):
            return ValueFromSVStrategy(
                existing_socket_value=spec.existing_socket_value,
                **kwargs,
            )
        elif not isinstance(spec.value, UnsetType):
            return ValueCreateStrategy(
                value=spec.value,
                **kwargs,
            )

    raise NotImplementedError(
        f"No strategy found that supports socket {socket.title} with spec {spec}"
    )


class FileCreateStrategy(SocketValueCreateStrategy):
    """Direct file upload strategy"""

    def __init__(
        self,
        *,
        files: list[str | Path],
        **kwargs,
    ):
        super().__init__(**kwargs)

        try:
            cleaned_files: list[Path] = clean_file_source(
                files,
                maximum_number=1,
            )
        except TooManyFiles as e:
            raise ValueError("You can only provide one file") from e

        self.content = cleaned_files[0]
        self.content_name = self.content.name

    def __call__(self):
        post_request = super().__call__()

        with open(self.content, "rb") as f:
            user_upload = self.client.uploads.upload_fileobj(
                fileobj=f, filename=self.content_name
            )

        post_request.user_upload = user_upload.api_url
        return post_request


class FileJSONCreateStrategy(SocketValueCreateStrategy):
    """Some JSON serializable Python object upload strategy"""

    def __init__(self, *, value: Any, **kwargs):
        super().__init__(**kwargs)

        try:
            json_bytes = json.dumps(value).encode()
        except TypeError:
            raise ValueError("Source is not JSON serializable") from None
        else:
            self.content = json_bytes
            self.content_name = self.socket.relative_path

    def __call__(self):
        post_request = super().__call__()

        with BytesIO(self.content) as f:
            user_upload = self.client.uploads.upload_fileobj(
                fileobj=f, filename=self.content_name
            )

        post_request.user_upload = user_upload.api_url
        return post_request


class FileFromSVCreateStrategy(SocketValueCreateStrategy):
    """Uses an existing SocketValue as source"""

    def __init__(
        self,
        *,
        socket_value: HyperlinkedComponentInterfaceValue,
        **kwargs,
    ):
        super().__init__(**kwargs)

        if socket_value.file is None:
            raise ValueError(
                f"{HyperlinkedComponentInterfaceValue.__name__} must have a file"
            )

        self.content_api_url = socket_value.file
        self.content_name = Path(socket_value.file).name

    def __call__(self):
        post_request = super().__call__()

        # Cannot link a file directly to file, so we download it first

        content = self._download_from_socket()

        with BytesIO(content) as f:
            user_upload = self.client.uploads.upload_fileobj(
                fileobj=f, filename=self.content_name
            )

        post_request.user_upload = user_upload.api_url
        return post_request

    def _download_from_socket(self) -> bytes:
        response_or_json = self.client(
            url=self.content_api_url,
            follow_redirects=True,
        )
        if isinstance(response_or_json, httpx.Response):
            return response_or_json.content
        else:
            # Else, the response is actually the JSON already
            return json.dumps(response_or_json).encode()


class ImageCreateStrategy(SocketValueCreateStrategy):
    """Direct image-file upload strategy"""

    def __init__(
        self,
        *,
        files: list[str | Path],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.files = clean_file_source(files)

    def __call__(self):
        post_request = super().__call__()

        with ExitStack() as stack:
            file_objects = [
                stack.enter_context(open(f, "rb")) for f in self.files
            ]
            filenames = [f.name for f in self.files]
            uploads = self.client.uploads.upload_multiple_fileobj(
                file_objects=file_objects,
                filenames=filenames,
            )

        post_request.user_uploads = [u.api_url for u in uploads]
        return post_request


class DICOMImageSetFileCreateStrategy(SocketValueCreateStrategy):

    _deidentifier_instance: DicomDeidentifier | None = None

    def __init__(
        self,
        *,
        files: list[str | Path],
        image_name: str,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.files = clean_file_source(files)
        self.image_name = image_name

        # Use the singleton deidentifier
        deidentifier = self.get_deidentifier()

        self.content = []
        try:
            for file in self.files:
                temp = SpooledTemporaryFile()
                # Add early to content so it gets closed on error
                self.content.append(temp)
                deidentifier.deidentify_file(file=file, output=temp)
                temp.seek(0)
        except Exception:
            self.close()
            raise

    def close(self):
        super().close()

        for temp in self.content:
            temp.close()

    @classmethod
    def get_deidentifier(cls) -> DicomDeidentifier:
        if cls._deidentifier_instance is None:
            cls._deidentifier_instance = DicomDeidentifier()
        return cls._deidentifier_instance

    def __call__(self):
        post_request = super().__call__()

        post_request.image_name = self.image_name

        filenames = [
            f"dicom_image_{idx}.dcm" for idx in range(len(self.content))
        ]
        uploads = self.client.uploads.upload_multiple_fileobj(
            file_objects=self.content,
            filenames=filenames,
        )
        post_request.user_uploads = [u.api_url for u in uploads]

        return post_request


class ImageFromImageCreateStrategy(SocketValueCreateStrategy):
    """Indirect via an existing image"""

    def __init__(
        self,
        *,
        existing_image_api_url: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        api_url = str(existing_image_api_url)

        # assert it is a valid URL
        self.content_api_url = httpx.URL(api_url)

        # assert we have access to the image
        self.client.images.detail(api_url=api_url)

    def __call__(self):
        post_request = super().__call__()
        post_request.image = str(self.content_api_url)
        return post_request


class ImageFromSVCreateStrategy(SocketValueCreateStrategy):
    """Indirect via an existing SocketValue"""

    def __init__(
        self,
        *,
        existing_socket_value: HyperlinkedComponentInterfaceValue,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        if existing_socket_value.image is None:
            raise ValueError(
                f"{HyperlinkedComponentInterfaceValue.__name__} must have an image"
            )

        api_url = existing_socket_value.image

        # assert it is a valid URL
        self.content_api_url = httpx.URL(api_url)

        # assert we have access to the image
        self.client.images.detail(api_url=api_url)

    def __call__(self):
        post_request = super().__call__()
        post_request.image = str(self.content_api_url)
        return post_request


class ValueFromFileCreateStrategy(SocketValueCreateStrategy):
    """Directly provided value"""

    def __init__(
        self,
        *,
        files: list[str | Path],
        **kwargs,
    ):
        super().__init__(**kwargs)

        try:
            cleaned_files = clean_file_source(files, maximum_number=1)
        except TooManyFiles as e:
            raise ValueError("You can only provide one file") from e

        self.content = cleaned_files[0]

        # Check parsable JSON, but for memory
        # considerations do not load it here yet
        with open(self.content) as fp:
            try:
                json.load(fp)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"File {self.content} is not a valid JSON file. "
                    "Nothing has been uploaded."
                ) from e

    def __call__(self):
        post_request = super().__call__()

        with open(self.content) as fp:
            post_request.value = json.load(fp)

        return post_request


class ValueFromSVStrategy(SocketValueCreateStrategy):

    def __init__(
        self,
        *,
        existing_socket_value: HyperlinkedComponentInterfaceValue,
        **kwargs,
    ):
        super().__init__(**kwargs)

        if existing_socket_value.value is None:
            raise ValueError(
                f"{HyperlinkedComponentInterfaceValue.__name__} must have a value"
            )

        self.content = existing_socket_value.value

    def __call__(self):
        post_request = super().__call__()
        post_request.value = self.content
        return post_request


class ValueCreateStrategy(SocketValueCreateStrategy):

    def __init__(self, *, value: Any, **kwargs):
        super().__init__(**kwargs)

        try:
            json.dumps(value)  # Check if it is JSON serializable
        except TypeError as e:
            raise ValueError(
                "Value is not JSON serializable. Nothing has been uploaded."
            ) from e

        self.content = value

    def __call__(self):
        post_request = super().__call__()
        post_request.value = self.content
        return post_request


class JobInputsCreateStrategy(BaseCreateStrategy):
    def __init__(
        self,
        *,
        algorithm: Algorithm,
        inputs: list[SocketValueSpec],
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.algorithm: Algorithm = algorithm
        self.input_strategies: list[SocketValueCreateStrategy] = []

        self._assert_matching_interface(inputs=inputs)

        try:
            for spec in inputs:
                socket_value_strategy = select_socket_value_strategy(
                    spec=spec,
                    client=self.client,
                )

                self.input_strategies.append(socket_value_strategy)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for strategy in self.input_strategies:
            strategy.close()

    def _assert_matching_interface(
        self, *, inputs: list[SocketValueSpec]
    ) -> None:

        # Find a matching interface
        matching_interface = None

        input_socket_slugs = {spec.socket_slug for spec in inputs}

        best_matching_sockets_count = 0
        best_matching_interface = None
        for interface in self.algorithm.interfaces:
            interface_socket_slugs = {
                socket.slug for socket in interface.inputs
            }
            matching_count = len(input_socket_slugs & interface_socket_slugs)
            if matching_count == len(interface_socket_slugs):
                # All input sockets are present in the interface
                matching_interface = interface
                break
            else:
                if matching_count > best_matching_sockets_count:
                    best_matching_sockets_count = matching_count
                    best_matching_interface = {
                        socket.slug for socket in interface.inputs
                    }

        if matching_interface is None:
            msg = f"No matching interface for sockets {input_socket_slugs} could be found."
            if best_matching_interface is not None:
                msg += f" The closest match is {best_matching_interface}."
            raise ValueError(msg)

    def __call__(self):
        result = []
        for s in self.input_strategies:
            result.append(s())
            s.close()
        return result
