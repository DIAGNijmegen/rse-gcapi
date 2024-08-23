import io
import json
from pathlib import Path
from typing import Optional, Union

from gcapi.models import (
    ArchiveItem,
    ComponentInterface,
    DisplaySet,
    HyperlinkedImage,
    SimpleImage,
)
from gcapi.typing import FileSource


class TooManyFiles(ValueError):
    pass


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


class ProtoCIV:
    def __new__(cls, *, interface: ComponentInterface, **__):
        # Determine the class specialization based on the interface's super_kind
        handler_class = {
            "image": ImageProtoCIV,
            "file": FileProtoCIV,
            "value": ValueProtoCIV,
        }.get(interface.super_kind.casefold())

        if handler_class is None:
            raise NotImplementedError(
                f"Unsupported interface super_kind: {interface.super_kind}"
            )

        if cls is not ProtoCIV:
            if cls is not handler_class:
                raise RuntimeError(
                    f"{cls} does not support interface "
                    f"super_kind: {interface.super_kind}"
                )
            return super().__new__(cls)

        return super().__new__(handler_class)

    def __init__(
        self,
        *,
        source: Union[FileSource, SimpleImage, HyperlinkedImage],
        interface: ComponentInterface,
        client_api,
    ):
        self.source = source
        self.interface = interface
        self.client_api = client_api
        self.cleaned = False

    def clean(self):
        self.cleaned = True
        return
        yield

    def get_post_value(
        self,
        civ_set: Optional[Union[DisplaySet, ArchiveItem]] = None,
    ):
        if not self.cleaned:
            yield from self.clean()

        return {"interface": self.interface.slug}  # noqa: B901


class FileProtoCIV(ProtoCIV):

    def clean(self):
        yield from super().clean()

        try:
            cleaned_sources = clean_file_source(self.source, maximum_number=1)
            self.content = cleaned_sources[0]
            self.content_name = self.content.name
        except FileNotFoundError as file_val_error:
            # Possibly a directly provided value
            if self.interface.kind.casefold() == "string":
                # !! WARNING !!
                # Incorrect paths being uploaded as content to a string interface can
                # easily bypass detection:
                #   - Platform JSON schemas for strings are typically underdefined
                #   - Files with super_kind require users to download them before
                #    viewing the content
                raise FileNotFoundError(
                    f"Interface kind {self.interface.kind} requires to be uploaded "
                    "as a file, replace the value with an existing file path"
                ) from file_val_error
            try:
                json_str = json.dumps(self.source)
            except TypeError:
                raise file_val_error
            self.content = io.StringIO(json_str)
            self.content_name = self.interface.relative_path

    def get_post_value(self, *_, **__):
        post = yield from super().get_post_value()

        with open(self.content, "rb") as f:
            user_upload = yield from self.client_api.uploads.upload_fileobj(
                fileobj=f, filename=self.content_name
            )
        post["user_upload"] = user_upload.api_url

        return post


class ImageProtoCIV(ProtoCIV):

    def clean(self):
        yield from super().clean()

        if isinstance(self.source, HyperlinkedImage):
            self.content = self.source
        elif isinstance(self.source, SimpleImage):
            self.content = yield from self.client_api.images.detail(
                pk=self.source.pk
            )
        else:
            self.content = clean_file_source(self.source)

    def _get_image_detail(self, pk):
        return

    def get_post_value(self, civ_set=None):
        post = yield from super().get_post_value()

        if isinstance(self.content, HyperlinkedImage):
            # Reuse the existing image
            post["image"] = self.content.api_url
            return post

        # Upload the image
        if civ_set is None:
            upload_session_data = {}  # No need to specify target
        elif isinstance(civ_set, DisplaySet):
            upload_session_data = {"display_set": civ_set.pk}
        elif isinstance(civ_set, ArchiveItem):
            upload_session_data = {"archive_item": civ_set.pk}
        else:
            raise NotImplementedError(
                f"{type(civ_set)} not supported for uploading images"
            )

        uploads = []
        for file in self.content:
            with open(file, "rb") as f:
                uploads.append(
                    (
                        yield from self.client_api.uploads.upload_fileobj(
                            fileobj=f, filename=file.name
                        )
                    )
                )
        upload_session_data["interface"] = self.interface.slug
        raw_image_upload_session = (
            yield from self.client_api.raw_image_upload_sessions.create(
                uploads=[u.api_url for u in uploads],
                **upload_session_data,
            )
        )

        if civ_set is None:
            post["session_upload"] = raw_image_upload_session
            return post


class ValueProtoCIV(ProtoCIV):

    def clean(self):
        yield from super().clean()

        try:
            cleaned_sources = clean_file_source(self.source, maximum_number=1)
            clean_source = cleaned_sources[0]
        except FileNotFoundError:
            # Directly provided value?
            json.dumps(self.source)  # Check if it is JSON serializable
            self.content = self.source
        else:
            # A singular json file
            with open(clean_source) as fp:
                self.content = json.load(fp)

    def get_post_value(self, *_, **__):
        post = yield from super().get_post_value()
        post["value"] = self.content
        return post
