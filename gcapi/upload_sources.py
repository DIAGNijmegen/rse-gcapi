import json
from pathlib import Path
from typing import Any, Optional, Union

from gcapi.models import ComponentInterface, SimpleImage

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
    return {
        "Image": ImageCIVSource,
        "File": FileCIVSource,
        "Value": ValueCIVSource,
    }[interface.super_kind]


FileSource = Union[Path, list[Path], str, list[str]]


class FileCIVSource:
    max_num_sources: Optional[int] = 1

    def __init__(self, source: FileSource):
        sources = [source] if not isinstance(source, list) else source

        if (
            self.max_num_sources is not None
            and len(sources) > self.max_num_sources
        ):
            raise TooManyFiles(
                f"Only {self.max_num_sources} are supported,"
                "you provided {len(sources)}"
            )

        self.content = self._validate_file_sources(sources)

    def _validate_file_sources(self, sources):
        validated = []
        for s in sources:
            path = Path(s) if isinstance(s, (str, Path)) else None
            if path and path.exists():
                validated.append(path)
            else:
                raise FileNotFoundError(s)
        return validated


class ImageCIVSource(FileCIVSource):
    max_num_sources = None

    simple_image = None

    def __init__(self, source: Union[FileSource, SimpleImage]):
        if isinstance(source, SimpleImage):
            self.content = source
        else:
            super().__init__(source)


class ValueCIVSource(FileCIVSource):
    max_num_sources = 1

    def __init__(self, source: Union[FileSource, Any]):
        try:
            super().__init__(source)
        except FileNotFoundError:
            # Directly provided value
            json.dumps(source)  # Check if it is JSON serializable
            self.content = source
        else:
            # A singular json file, read and parse the content
            with open(self.content[0]) as fp:
                self.content = json.load(fp)
