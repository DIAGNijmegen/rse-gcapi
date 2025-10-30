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
        existing_image_api_url: An API URL of an existing image
        existing_socket_value: Existing socket value to reuse
    """

    socket_slug: str

    value: Any = Unset
    files: list[str | Path] | UnsetType = Unset

    existing_image: str | UnsetType = Unset
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
            f"{self.__class__.__name__}({self.socket_slug=}, "
            f"{set_field_name}={set_field_value!r})"
        )


def clean_file_source(
    source: Any, *, maximum_number: int | None = None
) -> list[Path]:
    # Ensure we are handling a list
    sources = [source] if not isinstance(source, list) else source

    # Ensure items exist
    cleaned = []
    for s in sources:
        path = Path(s) if isinstance(s, (str, Path)) else None
        if path and path.exists():
            cleaned.append(path)
        else:
            raise FileNotFoundError(s)
    if not cleaned:
        raise FileNotFoundError("No files provided")

    # Ensure no more than can be handled
    if maximum_number is not None and len(sources) > maximum_number:
        raise TooManyFiles(
            f"The maximum is {maximum_number}, "
            f"you provided {maximum_number}: {sources}"
        )

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
    supported_super_kind: str
    socket: ComponentInterface

    spec: SocketValueSpec
    supported_spec_source_field: str

    def __init__(
        self,
        *,
        socket: ComponentInterface,
        spec: SocketValueSpec,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.socket = socket
        self.spec = spec

        assert (
            self.socket.slug == self.spec.socket_slug
        ), "SocketValueSpec socket_slug does not match the provided socket"

        if (
            self.socket.super_kind.casefold()
            != self.supported_super_kind.casefold()
        ):
            raise NotSupportedError(
                f"Socket {self.socket.title!r} is not supported by this strategy: "
                f"it has super_kind {self.socket.super_kind!r}, whereas we expected "
                f"{self.supported_super_kind!r}"
            )

        if spec.get_set_field_name() != self.supported_spec_source_field:
            raise NotSupportedError(
                f"Socket {self.socket.title!r} is not supported by this strategy: "
                f"it has source field {spec.get_set_field_name()!r}, whereas we expected "
                f"{self.supported_spec_source_field!r}"
            )

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


_strategy_registry = []


def register_socket_value_strategy(strategy_class):
    _strategy_registry.append(strategy_class)
    return strategy_class


class NotSupportedError(Exception):
    """
    Exception raised when a strategy is not supported for a given socket / source
    """

    pass


def select_socket_value_strategy(
    *,
    socket: ComponentInterface,
    spec: SocketValueSpec,
    client: Client,
) -> SocketValueCreateStrategy:
    for strategy_class in _strategy_registry:
        try:
            return strategy_class(socket=socket, spec=spec, client=client)
        except NotSupportedError:
            continue

    raise NotImplementedError(
        f"No strategy found that supports socket {socket.title} with spec {spec}"
    )


@register_socket_value_strategy
class FileCreateStrategy(SocketValueCreateStrategy):
    """Direct file upload strategy"""

    supported_super_kind = "file"
    supported_spec_source_field = "files"

    content: Path
    content_name: str

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        try:
            cleaned_files: list[Path] = clean_file_source(
                self.spec.files,
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


@register_socket_value_strategy
class FileJSONCreateStrategy(SocketValueCreateStrategy):
    """Some JSON serializable Python object upload strategy"""

    supported_super_kind = "file"
    supported_spec_source_field = "value"

    content: bytes
    content_name: str

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        try:
            json_bytes = json.dumps(self.spec.value).encode()
        except TypeError:
            raise NotSupportedError(
                "Source is not JSON serializable"
            ) from None
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


@register_socket_value_strategy
class FileFromSVCreateStrategy(SocketValueCreateStrategy):
    """Uses a SocketValue as source"""

    supported_super_kind = "file"
    supported_spec_source_field = "existing_socket_value"

    content_api_url: str
    content_name: str

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        socket_value = self.spec.existing_socket_value

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


@register_socket_value_strategy
class ImageCreateStrategy(SocketValueCreateStrategy):
    """Direct image-file upload strategy"""

    supported_super_kind = "image"
    supported_spec_source_field = "files"

    files: list[Path]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.files = clean_file_source(self.spec.files)

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


@register_socket_value_strategy
class ImageFromImageCreateStrategy(SocketValueCreateStrategy):
    """Indirect via an existing image"""

    supported_super_kind = "image"
    supported_spec_source_field = "existing_image"

    content_api_url: httpx.URL

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        api_url = str(self.spec.existing_image)

        # assert it is a valid URL
        self.content_api_url = httpx.URL(api_url)

        # assert we have access to the image
        self.client.images.detail(api_url=api_url)

    def __call__(self):
        post_request = super().__call__()
        post_request.image = str(self.content_api_url)
        return post_request


@register_socket_value_strategy
class ImageFromSVCreateStrategy(SocketValueCreateStrategy):
    """Indirect via an existing SocketValue"""

    supported_super_kind = "image"
    supported_spec_source_field = "existing_socket_value"

    content_api_url: httpx.URL

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        socket_value = self.spec.existing_socket_value

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


@register_socket_value_strategy
class ValueFromFileCreateStrategy(SocketValueCreateStrategy):
    """Directly provided value"""

    supported_super_kind = "value"
    supported_spec_source_field = "files"

    content: Path

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        try:
            files = clean_file_source(self.spec.files, maximum_number=1)
        except TooManyFiles as e:
            raise ValueError("You can only provide one file") from e

        self.content = files[0]

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


@register_socket_value_strategy
class ValueFromSVStrategy(SocketValueCreateStrategy):

    supported_super_kind = "value"
    supported_spec_source_field = "existing_socket_value"

    content: Any

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        socket_value = self.spec.existing_socket_value
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


@register_socket_value_strategy
class ValueCreateStrategy(SocketValueCreateStrategy):

    supported_super_kind = "value"
    supported_spec_source_field = "value"

    content: Any

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        try:
            json.dumps(self.spec.value)  # Check if it is JSON serializable
        except TypeError as e:
            raise ValueError(
                "Value is not JSON serializable. Nothing has been uploaded."
            ) from e

        self.content = self.spec.value

    def __call__(self):
        post_request = super().__call__()
        post_request.value = self.content
        return post_request


class JobInputsCreateStrategy(BaseCreateStrategy):
    input_strategies: list[SocketValueCreateStrategy]
    algorithm: Algorithm

    def __init__(
        self,
        *,
        algorithm: Algorithm,
        inputs: list[SocketValueSpec],
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.algorithm = algorithm
        self.input_strategies = []

        self._assert_matching_interface(inputs)

        socket_lookup: dict[str, ComponentInterface] = {
            socket.slug: socket
            for interface in self.algorithm.interfaces
            for socket in interface.inputs
        }

        for spec in inputs:
            socket_value_strategy = select_socket_value_strategy(
                spec=spec,
                socket=socket_lookup[spec.socket_slug],
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
