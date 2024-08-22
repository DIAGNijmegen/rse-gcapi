from typing import Any, Union

import gcapi.models

ValueDict = dict[Union[str, gcapi.models.ComponentInterface], Any]

ArchiveItemOrPk = Union[str, gcapi.models.ArchiveItem]
DisplaySetOrPk = Union[str, gcapi.models.DisplaySet]

CIVSet = Union[gcapi.models.DisplaySet, gcapi.models.ArchiveItem]
