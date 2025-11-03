from typing import Any, Union

import gcapi.models

SocketValueSetDescription = dict[str, Any]

SocketValueSet = Union[
    gcapi.models.DisplaySet,
    gcapi.models.DisplaySetPost,
    gcapi.models.ArchiveItem,
    gcapi.models.ArchiveItemPost,
]
