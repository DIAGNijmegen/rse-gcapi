from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import httpx

if TYPE_CHECKING:
    from gcapi.client import Client

from gcapi.exceptions import ObjectNotFound
from gcapi.models import (
    Algorithm,
    ComponentInterface,
    ComponentInterfaceValuePostRequest,
    HyperlinkedComponentInterfaceValue,
    HyperlinkedImage,
    UserUpload,
)
from gcapi.typing import FileSource, SocketValueSetDescription


class TooManyFiles(ValueError):
    pass


Empty = object()


def clean_file_source(
    source: FileSource, *, maximum_number: Optional[int] = None
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

    def __init__(
        self,
        *,
        socket: ComponentInterface,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.socket = socket

        if (
            self.socket.super_kind.casefold()
            != self.supported_super_kind.casefold()
        ):
            raise NotSupportedError(
                f"Socket {self.socket.title!r} is not supported by this strategy: "
                f"it has super_kind {self.socket.super_kind!r}, whereas we expected "
                f"{self.supported_super_kind!r}"
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
    socket,
    source,
    client,
) -> SocketValueCreateStrategy:
    for strategy_class in _strategy_registry:
        try:
            return strategy_class(socket=socket, source=source, client=client)
        except NotSupportedError:
            continue

    raise NotImplementedError(
        f"No strategy found that supports socket {socket.title} with source {source}"
    )


@register_socket_value_strategy
class FileCreateStrategy(SocketValueCreateStrategy):
    """Direct file upload strategy"""

    supported_super_kind = "file"

    content: Path
    content_name: str

    def __init__(self, source, **kwargs):
        super().__init__(**kwargs)

        try:
            cleaned_sources = clean_file_source(source, maximum_number=1)
        except FileNotFoundError as e:
            raise NotSupportedError from e
        except TooManyFiles as e:
            raise ValueError("Too many files provided") from e

        self.content = cleaned_sources[0]
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

    content: bytes
    content_name: str

    def __init__(self, source, **kwargs):
        super().__init__(**kwargs)

        if self.socket.kind.casefold() == "string":
            # Incorrect paths being uploaded as content to a String
            # socket can easily bypass detection.
            # We'll be overprotective and not allow via-value uploads.
            raise ValueError(
                f"Socket kind {self.socket.kind} requires to be uploaded "
                "as a file, replace the value with an existing file path"
            )
        try:
            json_bytes = json.dumps(source).encode()
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

    content_api_url: str
    content_name: str

    def __init__(self, source, **kwargs):
        super().__init__(**kwargs)

        if not isinstance(source, HyperlinkedComponentInterfaceValue):
            raise NotSupportedError("Source must be a SocketValue")

        if source.interface.pk != self.socket.pk:
            raise ValueError(
                f"Source {source.interface.title!r} does not "
                f"match socket {self.socket.title!r}"
            )

        if source.file is None:
            raise ValueError("SocketValue must have a file")

        self.content_api_url = source.file
        self.content_name = Path(source.file).name

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
    content: list[Path]

    def __init__(self, source, **kwargs):
        super().__init__(**kwargs)

        try:
            self.content = clean_file_source(source)
        except FileNotFoundError as e:
            raise NotSupportedError from e

    def __call__(self):
        post_request = super().__call__()

        uploads: list[UserUpload] = []
        for file in self.content:
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
class ImageFromSVCreateStrategy(SocketValueCreateStrategy):
    """Indirect via an HyperlinkedImage or SocketValue"""

    supported_super_kind = "image"
    content_api_url: httpx.URL

    def __init__(
        self,
        source: Any,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        if isinstance(source, HyperlinkedImage):
            url = source.api_url
        elif isinstance(source, HyperlinkedComponentInterfaceValue):
            if source.image is None:
                raise ValueError(
                    "HyperlinkedComponentInterfaceValue must have an image"
                )
            url = source.image
            if self.socket.pk != source.interface.pk:
                raise ValueError(
                    f"Source {source.interface.title!r} does not "
                    f"match socket {self.socket.title!r}"
                )
        elif isinstance(source, str):
            # Possibly an identifier (i.e. uuid or API url)
            try:
                image = self.client.images.detail(api_url=source)
            except ObjectNotFound:
                try:
                    image = self.client.images.detail(pk=source)
                except ObjectNotFound:
                    raise ValueError(
                        f"Image with pk or api_url {source} does not exist"
                    ) from None

            url = image.api_url
        else:
            raise NotSupportedError(
                "Source must be a HyperlinkedImage, a pk/api_url pointing to one "
                "or a HyperlinkedComponentInterfaceValue"
            )

        self.content_api_url = httpx.URL(url)

    def __call__(self):
        post_request = super().__call__()
        post_request.image = str(self.content_api_url)
        return post_request


@register_socket_value_strategy
class ValueFromFileCreateStrategy(SocketValueCreateStrategy):
    """Directly provided value"""

    supported_super_kind = "value"
    content: Path

    def __init__(self, source: Any, **kwargs):
        super().__init__(**kwargs)

        try:
            cleaned_sources = clean_file_source(source, maximum_number=1)
        except FileNotFoundError as e:
            raise NotSupportedError from e
        except TooManyFiles as e:
            raise ValueError("Too many files provided") from e

        self.content = cleaned_sources[0]

        # Check parsable JSON, but for
        # memory considerations do not load it yet

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
    content: Any

    def __init__(self, source: Any, **kwargs):
        super().__init__(**kwargs)

        if not isinstance(source, HyperlinkedComponentInterfaceValue):
            raise NotSupportedError("Source must be a SocketValue")

        if source.interface.pk != self.socket.pk:
            raise ValueError(
                f"Source {source.interface.title!r} does not "
                f"match socket {self.socket.title!r}"
            )

        if source.value is None:
            raise ValueError("SocketValue must have a value")

        self.content = source.value

    def __call__(self):
        post_request = super().__call__()

        post_request.value = self.content

        return post_request


@register_socket_value_strategy
class ValueCreateStrategy(SocketValueCreateStrategy):

    supported_super_kind = "value"
    content: Any

    def __init__(self, source: Any, **kwargs):
        super().__init__(**kwargs)

        try:
            json.dumps(source)  # Check if it is JSON serializable
        except TypeError as e:
            raise ValueError(
                "Source is not JSON serializable. Nothing has been uploaded."
            ) from e

        self.content = source

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
        inputs: SocketValueSetDescription,
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

        for socket_slug, source in inputs.items():
            socket_value_strategy = select_socket_value_strategy(
                source=source,
                socket=socket_lookup[socket_slug],
                client=self.client,
            )

            self.input_strategies.append(socket_value_strategy)

    def _assert_matching_interface(self, inputs) -> None:

        # Find a matching interface
        matching_interface = None

        input_keys = set(inputs.keys())

        best_matching_sockets_count = 0
        best_matching_interface = None
        for interface in self.algorithm.interfaces:
            interface_keys = {socket.slug for socket in interface.inputs}
            matching_count = len(input_keys & interface_keys)
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
            msg = f"No matching interface for sockets {input_keys} could be found."
            if best_matching_interface is not None:
                msg += f" The closest match is {best_matching_interface}."
            raise ValueError(msg)

    def __call__(self):
        return [s() for s in self.input_strategies]
