from typing import Protocol

import gcapi.models


class ReadableBuffer(Protocol):
    def read(self, size: int = ..., /) -> bytes: ...


SocketValuePostSet = gcapi.models.DisplaySetPost | gcapi.models.ArchiveItemPost


class UnsetType:
    pass


Unset = UnsetType()
