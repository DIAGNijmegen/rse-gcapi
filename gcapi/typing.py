from pathlib import Path
from typing import Any, Union

import gcapi.models

FileSource = Union[
    Path,
    list[Path],
    str,
    list[str],
]


SocketValueSetDescription = dict[str, Any]

SocketValueSet = Union[
    gcapi.models.DisplaySet,
    gcapi.models.DisplaySetPost,
    gcapi.models.ArchiveItem,
    gcapi.models.ArchiveItemPost,
]
