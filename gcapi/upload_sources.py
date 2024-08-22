import io
import json
from pathlib import Path
from typing import Any, Optional, Union

from httpx import AsyncClient, Client

from gcapi.models import (
    ArchiveItem,
    ComponentInterface,
    ComponentInterfaceValuePostRequest,
    DisplaySet,
    HyperlinkedImage,
    SimpleImage,
)


class TooManyFiles(ValueError):
    pass


FileSource = Union[
    Path,
    list[Path],
    str,
    list[str],
    HyperlinkedImage,
    SimpleImage,
]


def get_proto_civ_class(interface):
    # Determine the handler class based on the interface's super_kind
    handler_class = {
        "image": ImageProtoCIV,
        "file": FileProtoCIV,
        "value": ValueProtoCIV,
    }.get(interface.super_kind.casefold())

    if handler_class is None:
        raise ValueError(
            f"Unsupported interface super_kind: {interface.super_kind}"
        )

    # Return an instance of the appropriate handler
    return handler_class


def clean_file_source(
    source: FileSource, maximum_number: Optional[int] = None
):
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


class ProtoCIV:
    def __init__(
        self,
        interface: ComponentInterface,
        client: Union[Client, AsyncClient],
    ):
        self.interface = interface
        self.client = client

    def get_post_value(
        self,
        civ_set: Optional[Union[DisplaySet, ArchiveItem]] = None,
    ) -> ComponentInterfaceValuePostRequest:
        return ComponentInterfaceValuePostRequest(
            interface=self.interface.slug,
            value=None,
            file=None,
            image=None,
            upload_session=None,
            user_upload=None,
        )


class FileProtoCIV(ProtoCIV):
    def __init__(self, source: FileSource, **kwargs):
        super().__init__(**kwargs)

        try:
            cleaned_sources = clean_file_source(source, maximum_number=1)
            self.content = cleaned_sources[0]
            self.content_name = self.content.name
        except FileNotFoundError as file_val_error:
            # Possibly a directly provided value
            if self.interface.kind.casefold() == "string":
                # Incorrect paths being uploaded as content to a string interface can
                # easily bypass detection because:
                #   - Platform JSON schemas for strings are typically underdefined
                #   - Files with super_kind require users to download them before
                #    viewing the content.
                raise FileNotFoundError(
                    f"Interface kind {self.interface.kind} requires to be upload "
                    "as a file, replace value with an existing file path"
                ) from file_val_error
            try:
                json_str = json.dumps(source)
            except TypeError:
                raise file_val_error
            self.content = io.StringIO(json_str)
            self.content_name = self.interface.relative_path

    def get_post_value(self, *_, **__):
        post = super().process()

        with open(self.content, "rb") as f:
            user_upload = yield from self.client.uploads.upload_fileobj(
                fileobj=f, filename=self.content_name
            )
        post.user_upload = user_upload.api_url

        return post


class ImageProtoCIV(ProtoCIV):
    def __init__(
        self,
        source: Union[FileSource, SimpleImage, HyperlinkedImage],
        **kwargs,
    ):
        super().__init__(**kwargs)

        if isinstance(source, HyperlinkedImage):
            self.content = source
        elif isinstance(source, SimpleImage):
            self.content = self._get_image_detail(source.pk)
        else:
            self.content = clean_file_source(source)

    def _get_image_detail(self, pk):
        return (yield from self.client.images.detail(pk=pk))

    def get_post_value(self, civ_set=None):
        post = super().get_post_value()

        if isinstance(self.content, HyperlinkedImage):
            # Reuse the existing image
            post.image = self.content.api_url
            return post

        # Upload the image
        uploads = []
        for file in self.content:
            with open(file, "rb") as f:
                uploads.append(
                    (
                        yield from self.client.uploads.upload_fileobj(
                            fileobj=f, filename=file.name
                        )
                    )
                )

        upload_session_data = {
            "interface": self.interface.slug,
        }

        if civ_set is None:
            pass  # No need to specify target
        elif isinstance(civ_set, DisplaySet):
            upload_session_data["display_set"] = civ_set.pk
        elif isinstance(civ_set, ArchiveItem):
            upload_session_data["archive_item"] = civ_set.pk
        else:
            raise NotImplementedError(
                f"{type(civ_set)} not supporting for uploading image"
            )

        raw_image_upload_session = (
            yield from self.client.raw_image_upload_sessions.create(
                uploads=[u.api_url for u in uploads],
                **upload_session_data,
            )
        )

        if civ_set is None:
            post.session_upload = raw_image_upload_session

        return post


class ValueProtoCIV(ProtoCIV):
    def __init__(self, source: Union[FileSource, Any], **kwargs):
        super().__init__(**kwargs)

        try:
            cleaned_sources = clean_file_source(source, maximum_number=1)
            clean_source = cleaned_sources[0]
        except FileNotFoundError:
            # Directly provided value?
            json.dumps(source)  # Check if it is JSON serializable
            self.content = source
        else:
            # A singular json file
            with open(clean_source) as fp:
                self.content = json.load(fp)

    def get_post_value(
        self,
        *_,
        **__,
    ):
        data = super().get_post_value()
        data.value = self.content
        return data
