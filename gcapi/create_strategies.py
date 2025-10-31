from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from gcapi.client import Client

from gcapi.models import (
    Algorithm,
    ComponentInterface,
    ComponentInterfaceValuePostRequest,
    HyperlinkedComponentInterfaceValue,
    UserUpload,
)


class TooManyFiles(ValueError):
    pass


class UnsetType:
    pass


Unset = UnsetType()


@dataclass
class SocketValueSpec:
    """
    Specification for a socket value which provides exactly one source
    in order to create the SocketValue.

    Args:
        socket_slug: The slug of the socket (required)

        value: Direct source value to set (can be None)
        files: List of source file paths for file/image uploads
        existing_image_api_url: An API URL of an existing image to reuse
        existing_socket_value: Existing socket value that can be reused
    """

    socket_slug: str

    value: Any = Unset
    files: list[str | Path] | UnsetType = Unset

    existing_image_api_url: str | UnsetType = Unset
    existing_socket_value: HyperlinkedComponentInterfaceValue | UnsetType = (
        Unset
    )

    def __post_init__(self):
        """Validate that the specification is correct."""
        # Get all fields except socket_slug
        sources = []

        for field_name, field_value in self.__dict__.items():
            if field_name == "socket_slug":
                continue
            if field_value is not Unset:
                sources.append(field_name)

        if len(sources) > 1:
            raise ValueError(
                f"Only one source can be specified, but got: {', '.join(sources)}. "
                f"Please specify only one of the available source fields."
            )

        if len(sources) == 0:
            raise ValueError(
                "At least one source must be specified. "
                "Please provide one of the available source fields."
            )

    def get_set_field_name(self) -> str:
        for field_name, field_value in self.__dict__.items():
            if field_name == "socket_slug":
                continue
            if field_value is not Unset:
                return field_name
        raise RuntimeError("No source field is set, this should not happen.")

    def __repr__(self) -> str:
        set_field_name = self.get_set_field_name()
        set_field_value = getattr(self, set_field_name)
        return (
            f"{self.__class__.__name__}(socket_slug={self.socket_slug}, "
            f"{set_field_name}={set_field_value!r})"
        )


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
    """

    client: Client

    def __init__(self, *, client):
        self.client = client

    def __call__(self) -> Any: ...


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

        if not isinstance(
            socket_value,
            HyperlinkedComponentInterfaceValue,
        ):
            raise ValueError(
                f"existing_socket_value must be a {HyperlinkedComponentInterfaceValue.__name__}"
            )

        if socket_value.interface.pk != self.socket.pk:
            raise ValueError(
                f"Source {socket_value.interface.title!r} does not "
                f"match socket {self.socket.title!r}"
            )

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

        uploads: list[UserUpload] = []
        for file in self.files:
            with open(file, "rb") as f:
                uploads.append(
                    self.client.uploads.upload_fileobj(
                        fileobj=f, filename=file.name
                    )
                )
        raw_image_upload_session = (
            self.client.raw_image_upload_sessions.create(
                uploads=[u.api_url for u in uploads],
            )
        )

        post_request.upload_session = raw_image_upload_session.api_url
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

        socket_value = existing_socket_value

        if not isinstance(
            socket_value,
            HyperlinkedComponentInterfaceValue,
        ):
            raise ValueError(
                f"existing_socket_value must be a {HyperlinkedComponentInterfaceValue.__name__}"
            )

        if socket_value.interface.pk != self.socket.pk:
            raise ValueError(
                f"Source {socket_value.interface.title!r} does not "
                f"match socket {self.socket.title!r}"
            )

        if socket_value.image is None:
            raise ValueError(
                f"{HyperlinkedComponentInterfaceValue.__name__} must have an image"
            )

        api_url = socket_value.image

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

        socket_value = existing_socket_value
        if not isinstance(socket_value, HyperlinkedComponentInterfaceValue):
            raise ValueError(
                f"existing_socket_value must be a {HyperlinkedComponentInterfaceValue.__name__}"
            )

        if socket_value.interface.pk != self.socket.pk:
            raise ValueError(
                f"Source {socket_value.interface.title!r} does not "
                f"match socket {self.socket.title!r}"
            )

        if socket_value.value is None:
            raise ValueError(
                f"{HyperlinkedComponentInterfaceValue.__name__} must have a value"
            )

        self.content = socket_value.value

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

        self._assert_matching_interface(inputs)

        for spec in inputs:
            socket_value_strategy = select_socket_value_strategy(
                spec=spec,
                client=self.client,
            )

            self.input_strategies.append(socket_value_strategy)

    def _assert_matching_interface(
        self, inputs: list[SocketValueSpec]
    ) -> None:

        # Find a matching interface
        matching_interface = None

        socket_slugs = {spec.socket_slug for spec in inputs}

        best_matching_sockets_count = 0
        best_matching_interface = None
        for interface in self.algorithm.interfaces:
            interface_keys = {socket.slug for socket in interface.inputs}
            matching_count = len(socket_slugs & interface_keys)
            if matching_count == len(interface_keys):
                # All input keys are present in the interface
                matching_interface = interface
                break
            else:
                if matching_count > best_matching_sockets_count:
                    best_matching_sockets_count = matching_count
                    best_matching_interface = {
                        socket.slug for socket in interface.inputs
                    }

        if matching_interface is None:
            msg = f"No matching interface for sockets {socket_slugs} could be found."
            if best_matching_interface is not None:
                msg += f" The closest match is {best_matching_interface}."
            raise ValueError(msg)

    def __call__(self):
        return [s() for s in self.input_strategies]
