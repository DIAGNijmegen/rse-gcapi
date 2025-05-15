from pathlib import Path
from typing import Union

import gcapi.models

FileSource = Union[
    Path,
    list[Path],
    str,
    list[str],
]


SocketValueSetDescription = dict[
    Union[str, gcapi.models.ComponentInterface],
    Union[
        FileSource,
        gcapi.models.HyperlinkedComponentInterfaceValue,
        gcapi.models.HyperlinkedImage,
    ],
]

SocketValueSet = Union[
    gcapi.models.DisplaySet,
    gcapi.models.DisplaySetPost,
    gcapi.models.ArchiveItem,
    gcapi.models.ArchiveItemPost,
]
