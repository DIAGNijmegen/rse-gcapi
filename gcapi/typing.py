from typing import Protocol

import gcapi.models


class ReadableBuffer(Protocol):
    def read(self, size: int = ..., /) -> bytes: ...

    def seek(self, offset: int, whence: int = ..., /) -> int: ...

    def tell(self) -> int: ...


SocketValuePostSet = gcapi.models.DisplaySetPost | gcapi.models.ArchiveItemPost
