import io
import json
from pathlib import Path
from typing import Optional, Union

import httpx

from gcapi.models import (
    Algorithm,
    ArchiveItem,
    ArchiveItemPost,
    ComponentInterface,
    ComponentInterfaceValuePostRequest,
    DisplaySet,
    DisplaySetPost,
    HyperlinkedComponentInterfaceValue,
    HyperlinkedImage,
)
from gcapi.typing import FileSource, SocketValueSet, SocketValueSetDescription


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

    Each strategy has a `prepare()` function to support batch preparing
    before things actually land on Grand Challenge. Preparing should **not**
    create anything on Grand Challenge.

    Calling the strategy will, if applicable, upload contents and hence cause
    objects to be created on Grand Challenge. Calling the strategy will return
    a dict that describes how others items can hook up to the created items.
    """

    def __init__(self, *, client):
        self.client = client
        self.prepared = False

    @property
    def hybrid_client_api(self):
        """Return the original client API definitions that are async/sync hybrids"""
        return self.client._ClientBase__org_api_meta

    def prepare(self):
        """Ensure that the strategy can be executed"""
        self.prepared = True
        return
        yield

    def __call__(self):
        """
        If applicable, upload any contents and returns an item
        that can be used in POSTs that would use the created objects.
        """
        if not self.prepared:
            yield from self.prepare()


class SocketValueCreateStrategy(BaseCreateStrategy):

    def __new__(cls, *, socket: ComponentInterface, **__):
        # Determine the class specialization based on the interface's super_kind.
        handler_class = {
            "image": ImageSocketValueCreateStrategy,
            "file": FileSocketValueCreateStrategy,
            "value": ValueSocketValueCreateStrategy,
        }.get(socket.super_kind.casefold())

        if handler_class is None:
            raise NotImplementedError(
                f"Unsupported interface super_kind: {socket.super_kind}"
            )

        if cls is not SocketValueCreateStrategy:
            # Specialized class: double check if it supports the interface.
            if cls is not handler_class:
                raise RuntimeError(
                    f"{cls} does not support interface "
                    f"super_kind: {socket.super_kind}"
                )
            return super().__new__(cls)

        return super().__new__(handler_class)

    def __init__(
        self,
        *,
        source: Union[
            FileSource, HyperlinkedComponentInterfaceValue, HyperlinkedImage
        ],
        socket: ComponentInterface,
        parent: Optional[SocketValueSet] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.source = source
        self.socket = socket
        self.parent = parent

    def prepare(self):
        yield from super().prepare()

        if (
            isinstance(self.source, HyperlinkedComponentInterfaceValue)
            and self.source.interface.pk != self.socket.pk
        ):
            raise ValueError(
                f"Source {self.source.interface.title!r} does not "
                f"match socket {self.socket.title!r}"
            )

    def __call__(self):
        yield from super().__call__()

        return ComponentInterfaceValuePostRequest(  # noqa: B901
            interface=self.socket.slug,
            value=None,
            file=None,
            image=None,
            upload_session=None,
            user_upload=None,
        )


class FileSocketValueCreateStrategy(SocketValueCreateStrategy):

    def prepare(self):
        yield from super().prepare()

        if isinstance(self.source, HyperlinkedComponentInterfaceValue):
            self.content_name = Path(self.source.file).name
        else:
            try:
                self._prepare_from_local_file(file=self.source)
            except FileNotFoundError as file_val_error:
                self._prepare_from_provided_value(
                    value=self.source, file_val_error=file_val_error
                )

    def _prepare_from_local_file(self, file):
        cleaned_sources = clean_file_source(file, maximum_number=1)
        self.content = cleaned_sources[0]
        self.content_name = self.content.name

    def _prepare_from_provided_value(self, value, file_val_error):
        if self.socket.kind.casefold() == "string":
            # Incorrect paths being uploaded as content to a String
            # socket can easily bypass detection.
            # We'll be overprotective and not allow via-value uploads.
            raise FileNotFoundError(
                f"Socket kind {self.socket.kind} requires to be uploaded "
                "as a file, replace the value with an existing file path"
            ) from file_val_error
        try:
            json_str = json.dumps(value)
        except TypeError:
            raise file_val_error

        self.content = io.StringIO(json_str)
        self.content_name = self.socket.relative_path

    def _create_from_socket(self, post_request):
        from gcapi.client import ClientBase

        # Cannot link a file directly to file, so we download it first
        response_or_json = yield from ClientBase.__call__(
            self.client,
            url=self.source.file,
            follow_redirects=True,
        )
        if isinstance(response_or_json, httpx.Response):
            fileobj = io.StringIO(response_or_json.content.decode("utf-8"))
        else:
            # Else, the response is actually the JSON
            fileobj = io.StringIO(json.dumps(response_or_json))

        user_upload = yield from self.hybrid_client_api.uploads.upload_fileobj(
            fileobj=fileobj, filename=self.content_name
        )

        post_request.user_upload = user_upload.api_url
        return post_request

    def __call__(self):
        post_request = yield from super().__call__()

        if isinstance(self.source, HyperlinkedComponentInterfaceValue):
            return (yield from self._create_from_socket(post_request))
        else:
            with open(self.content, "rb") as f:
                user_upload = (
                    yield from self.hybrid_client_api.uploads.upload_fileobj(
                        fileobj=f, filename=self.content_name
                    )
                )
            post_request.user_upload = user_upload.api_url
            return post_request


class ImageSocketValueCreateStrategy(SocketValueCreateStrategy):

    def prepare(self):
        yield from super().prepare()

        if isinstance(self.source, HyperlinkedImage):
            self.content = self.source
        elif (
            isinstance(self.source, HyperlinkedComponentInterfaceValue)
            and self.source.image is not None
        ):
            self.content = yield from self.hybrid_client_api.images.detail(
                api_url=self.source.image
            )
        else:
            self.content = clean_file_source(self.source)

    def __call__(self):
        post_request = yield from super().__call__()

        if isinstance(self.content, HyperlinkedImage):
            # Reuse the existing image
            post_request.image = self.content.api_url
            return post_request

        # Upload the image
        if self.parent is None:
            # No need to specify target
            upload_session_data = {}
        elif isinstance(self.parent, (DisplaySet, DisplaySetPost)):
            upload_session_data = {
                "display_set": self.parent.pk,
                "interface": self.socket.slug,
            }
        elif isinstance(self.parent, (ArchiveItem, ArchiveItemPost)):
            upload_session_data = {
                "archive_item": self.parent.pk,
                "interface": self.socket.slug,
            }
        else:
            raise NotImplementedError(
                f"{type(self.parent)} not supported for uploading images"
            )

        uploads = []
        for file in self.content:
            with open(file, "rb") as f:
                uploads.append(
                    (
                        yield from self.hybrid_client_api.uploads.upload_fileobj(
                            fileobj=f, filename=file.name
                        )
                    )
                )
        raw_image_upload_session = (
            yield from self.hybrid_client_api.raw_image_upload_sessions.create(
                uploads=[u.api_url for u in uploads],
                **upload_session_data,
            )
        )

        if self.parent is None:
            post_request.upload_session = raw_image_upload_session.api_url
            return post_request
        else:
            return Empty


class ValueSocketValueCreateStrategy(SocketValueCreateStrategy):

    def prepare(self):
        yield from super().prepare()

        if isinstance(self.source, HyperlinkedComponentInterfaceValue):
            self.content = self.source.value
        else:
            try:
                self._prepare_from_local_file(file=self.source)
            except FileNotFoundError:
                json.dumps(self.source)  # Check if it is JSON serializable
                self.content = self.source

    def _prepare_from_local_file(self, file):
        cleaned_sources = clean_file_source(file, maximum_number=1)
        self.content = cleaned_sources[0]

        with open(self.content) as fp:
            self.content = json.load(fp)

    def __call__(self):
        post_request = yield from super().__call__()
        post_request.value = self.content
        return post_request


class JobInputsCreateStrategy(BaseCreateStrategy):
    def __init__(
        self,
        *,
        algorithm: Union[str, Algorithm],
        inputs: SocketValueSetDescription,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.algorithm = algorithm
        self.inputs = inputs

        self.input_strategies: list[SocketValueCreateStrategy] = []

    def prepare(self):
        yield from super().prepare()

        if isinstance(self.algorithm, str):
            self.algorithm = (
                yield from self.hybrid_client_api.algorithms.detail(
                    slug=self.algorithm
                )
            )

        # Find a matching interface
        matching_interface = None

        input_keys = set(self.inputs.keys())

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

        socket_lookup = {
            socket.slug: socket
            for interface in self.algorithm.interfaces
            for socket in interface.inputs
        }

        for socket_slug, source in self.inputs.items():
            socket_value_strategy = SocketValueCreateStrategy(
                source=source,
                socket=socket_lookup[socket_slug],
                client=self.client,
            )
            yield from socket_value_strategy.prepare()

            self.input_strategies.append(socket_value_strategy)

    def __call__(self):
        yield from super().__call__()

        input_post_requests = []
        for strat in self.input_strategies:
            post_request = yield from strat()
            if post_request is not Empty:
                input_post_requests.append(post_request)

        return input_post_requests  # noqa: B901
