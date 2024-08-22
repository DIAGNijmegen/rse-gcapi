import io
import json
from pathlib import Path
from typing import Any, Optional, Union

from httpx import AsyncClient, Client

from gcapi.models import (
    ComponentInterface,
    ComponentInterfaceValuePostRequest,
    HyperlinkedImage,
    SimpleImage,
)

# First, wrap every potential CIV in a call that has a basic validation call

# potential CIV can be called that returns something that can be added to the civ.

# This is dict with
# "user_upload"
# "upload_session"
# "image"
# "value"
# based on the ComponentInterfaceValuePostSerializer

# Note if we upload an image, it will be set after a while.
# As such, we'll need to provide the display set it will be added to.


class TooManyFiles(ValueError):
    pass


def interface_to_civ_source(interface: ComponentInterface):
    handler = {
        "image": ImageCIVSource,
        "file": FileCIVSource,
        "value": ValueCIVSource,
    }[interface.super_kind.casefold()]

    return handler


FileSource = Union[Path, list[Path], str, list[str]]


class BaseCIVSource:
    interface: ComponentInterface
    client: Union[Client, AsyncClient]

    def __init__(self, interface, client):
        self.interface = interface
        self.client = client

    def process(self) -> ComponentInterfaceValuePostRequest:
        return ComponentInterfaceValuePostRequest(
            interface=self.interface.slug,
            value=None,
            file=None,
            image=None,
            upload_session=None,
            user_upload=None,
        )


def clean_file_source(
    source: FileSource, maximum_number: Optional[int] = None
):
    sources = [source] if not isinstance(source, list) else source

    validated = []
    for s in sources:
        path = Path(s) if isinstance(s, (str, Path)) else None
        if path and path.exists():
            validated.append(path)
        else:
            raise FileNotFoundError(s)

    if maximum_number is not None and len(sources) > maximum_number:
        raise TooManyFiles(
            f"The maximum is {maximum_number}, "
            f"you provided {maximum_number}: {sources}"
        )

    return validated


class FileCIVSource(BaseCIVSource):
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

    def process(self):
        post = super().process()

        with open(self.content, "rb") as f:
            user_upload = yield from self.client.uploads.upload_fileobj(
                fileobj=f, filename=self.content_name
            )
        post.user_upload = user_upload.api_url

        return post


class ImageCIVSource(BaseCIVSource):

    def __init__(
        self,
        source: Union[FileSource, SimpleImage, HyperlinkedImage],
        **kwargs,
    ):
        super().__init__(**kwargs)

        if isinstance(source, (SimpleImage, HyperlinkedImage)):
            self.content = self.client.images.detail(pk=source.pk)
        else:
            self.content = clean_file_source(source)

    def process(self):
        post = super().process()

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

        raw_image_upload = (
            yield from self.client.raw_image_upload_sessions.create(
                uploads=[u.api_url for u in uploads],
            )
        )

        post.upload_session = raw_image_upload.api_url

        return post


class ValueCIVSource(BaseCIVSource):
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

    def process(self):
        data = super().process()
        data.value = self.content
        return data
