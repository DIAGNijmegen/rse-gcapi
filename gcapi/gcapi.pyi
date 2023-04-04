from typing import AsyncGenerator, Generator

from gcapi.apibase import PageResult
from gcapi.models import Algorithm

class SyncAlgorithmAPI:
    def page(self) -> PageResult[Algorithm]: ...
    def iterate_all(self) -> Generator[Algorithm, None, None]: ...

class Client:
    algorithms: SyncAlgorithmAPI

class AsyncAlgorithmAPI:
    async def page(self) -> PageResult[Algorithm]: ...
    def iterate_all(self) -> AsyncGenerator[Algorithm, None]: ...

class AsyncClient:
    algorithms: AsyncAlgorithmAPI
