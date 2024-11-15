import io
import json
from pathlib import Path
from typing import Optional, Union

from gcapi.models import (
    Algorithm,
    ArchiveItem,
    ArchiveItemPost,
    ComponentInterface,
    DisplaySet,
    DisplaySetPost,
    HyperlinkedComponentInterfaceValue,
    HyperlinkedImage,
)
from gcapi.typing import CIVSet, CIVSetDescription, FileSource


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


class BaseProtoModel:
    """
    Base class for proto models for component-interface values (CIVs).

    The raison d'être is to re-use code for different client helper
    functions such as upload_to_reader_study() or update_display_set().

    Proto models have two distinct functions:
    - `clean()`
    - `gen_post_request()`

    The `gen_post_request()` ensures that `clean()` has been called.

    This supports batch cleaning before things actually land on Grand Challenge.
    """

    def __init__(self, *, client_api):
        self.client_api = client_api
        self.cleaned = False

    def clean(self):
        """Ensure that things are ready to be uploaded."""
        self.cleaned = True
        return
        yield

    def gen_post_request(self):
        """
        If applicable, upload any contents and return a dict
        that can be used in POSTs.
        """

        # TODO: convert this to use the proper PostRequest models;
        # requires in-depth changes to client

        if not self.cleaned:
            yield from self.clean()


class ProtoCIV(BaseProtoModel):

    def __new__(cls, *, interface: ComponentInterface, **__):
        # Determine the class specialization based on the interface's super_kind.
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
            # Specialized class: double check if it supports the interface.
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
        source: Union[
            FileSource, HyperlinkedComponentInterfaceValue, HyperlinkedImage
        ],
        interface: ComponentInterface,
        parent: Optional[CIVSet] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.source = source
        self.interface = interface
        self.parent = parent

    def gen_post_request(self):
        yield from super().gen_post_request()

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
                # Incorrect paths being uploaded as content to a String
                # interface can easily bypass detection.
                # We'll be overprotective and not allow via-value uploads.
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

    def gen_post_request(self):
        item = yield from super().gen_post_request()

        with open(self.content, "rb") as f:
            user_upload = yield from self.client_api.uploads.upload_fileobj(
                fileobj=f, filename=self.content_name
            )
        item["user_upload"] = user_upload.api_url

        return item


class ImageProtoCIV(ProtoCIV):

    def clean(self):
        yield from super().clean()

        if isinstance(self.source, HyperlinkedImage):
            self.content = self.source
        elif (
            isinstance(self.source, HyperlinkedComponentInterfaceValue)
            and self.source.image is not None
        ):
            self.content = yield from self.client_api.images.detail(
                api_url=self.source.image
            )
        else:
            self.content = clean_file_source(self.source)

    def gen_post_request(self):
        item = yield from super().gen_post_request()

        if isinstance(self.content, HyperlinkedImage):
            # Reuse the existing image
            item["image"] = self.content.api_url
            return item

        # Upload the image
        if self.parent is None:
            # No need to specify target
            upload_session_data = {}
        elif isinstance(self.parent, (DisplaySet, DisplaySetPost)):
            upload_session_data = {
                "display_set": self.parent.pk,
                "interface": self.interface.slug,
            }
        elif isinstance(self.parent, (ArchiveItem, ArchiveItemPost)):
            upload_session_data = {
                "archive_item": self.parent.pk,
                "interface": self.interface.slug,
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
                        yield from self.client_api.uploads.upload_fileobj(
                            fileobj=f, filename=file.name
                        )
                    )
                )
        raw_image_upload_session = (
            yield from self.client_api.raw_image_upload_sessions.create(
                uploads=[u.api_url for u in uploads],
                **upload_session_data,
            )
        )

        if self.parent is None:
            item["upload_session"] = raw_image_upload_session.api_url
            return item
        else:
            return Empty


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

    def gen_post_request(self):
        item = yield from super().gen_post_request()
        item["value"] = self.content
        return item


class ProtoJob(BaseProtoModel):
    def __init__(
        self,
        *,
        algorithm: Union[str, Algorithm],
        inputs: CIVSetDescription,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.algorithm = algorithm
        self.inputs = inputs

        self.proto_civs: list[ProtoCIV] = []

    def clean(self):
        yield from super().clean()

        if isinstance(self.algorithm, str):
            self.algorithm = yield from self.client_api.algorithms.detail(
                slug=self.algorithm
            )

        interface_lookup = {ci.slug: ci for ci in self.algorithm.inputs}

        for ci in self.algorithm.inputs:
            if ci.slug not in self.inputs and ci.default_value is None:
                raise ValueError(f"{ci} is not provided")

        for ci_slug in self.inputs.keys():
            if ci_slug not in interface_lookup:
                raise ValueError(
                    f"{ci_slug} is not an input interface for this algorithm"
                )

        for ci_slug, source in self.inputs.items():
            civ = ProtoCIV(
                source=source,
                interface=interface_lookup[ci_slug],
                client_api=self.client_api,
            )
            yield from civ.clean()

            self.proto_civs.append(civ)

    def gen_post_request(self):
        yield from super().gen_post_request()

        inputs = []
        for civ in self.proto_civs:
            saved_civ = yield from civ.gen_post_request()
            if saved_civ is not Empty:
                inputs.append(saved_civ)

        return (  # noqa: B901
            yield from self.client_api.algorithm_jobs.create(
                algorithm=self.algorithm.api_url,
                inputs=inputs,
            )
        )
