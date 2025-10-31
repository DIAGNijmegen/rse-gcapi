from pathlib import Path
from typing import Union

import gcapi.models

FileSource = Union[
    Path,
    list[Path],
    str,
    list[str],
]

SocketValuePostSet = gcapi.models.DisplaySetPost | gcapi.models.ArchiveItemPost
