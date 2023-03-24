import collections
from typing import (
    Any,
    Dict,
    Generator,
    Generic,
    List,
    Optional,
    Sequence,
    Type,
    TypeVar,
    overload,
)
from urllib.parse import urljoin

from httpx import URL, HTTPStatusError
from httpx._types import URLTypes

from .exceptions import MultipleObjectsReturned, ObjectNotFound
from .model_base import BaseModel
from .sync_async_hybrid_support import (
    CallCapture,
    CapturedCall,
    mark_generator,
)

T = TypeVar("T")


class ClientInterface:
    @property
    def base_url(self) -> URL:
        ...

    @base_url.setter
    def base_url(self, v: URLTypes):
        ...

    def validate_url(self, url):
        ...

    def __call__(
        self,
        method="GET",
        url="",
        path="",
        params=None,
        json=None,
        extra_headers=None,
        files=None,
        data=None,
    ) -> Generator[CapturedCall, Any, Any]:
        raise NotImplementedError


class Common:
    _client: Optional[ClientInterface] = None
    base_path = ""
    model: Optional[Type[BaseModel]] = None

    yield_request = CallCapture()


class APIBase(Common):
    sub_apis: Dict[str, Type["APIBase"]] = {}

    def __init__(self, client):
        if isinstance(self, ModifiableMixin):
            ModifiableMixin.__init__(self)

        self._client = client

        for k, api in list(self.sub_apis.items()):
            setattr(self, k, api(self._client))

    def list(self, params=None):
        result = yield self.yield_request(
            method="GET", path=self.base_path, params=params
        )
        return result

    def page(self, offset=0, limit=100, params=None):
        if params is None:
            params = {}

        params["offset"] = offset
        params["limit"] = limit

        response = yield self.yield_request(
            method="GET", path=self.base_path, params=params
        )

        results = [self.model(**result) for result in response["results"]]

        return PageResult(
            offset=offset,
            limit=limit,
            total_count=response["count"],
            results=results,
        )

    @mark_generator
    def iterate_all(self, params=None):
        req_count = 100
        offset = 0
        while True:
            current_list = yield from self.page(
                offset=offset,
                limit=req_count,
                params=params,
            )
            if len(current_list) == 0:
                break
            yield from current_list
            offset += req_count

    def detail(self, pk=None, **params):
        if all((pk, params)):
            raise ValueError("Only one of pk or params must be specified")

        if pk is not None:
            try:
                result = yield self.yield_request(
                    method="GET", path=urljoin(self.base_path, pk + "/")
                )
                return self.model(**result)
            except HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise ObjectNotFound from e
                else:
                    raise e
        else:
            results = yield from self.page(params=params)
            results = list(results)

            if len(results) == 1:
                return results[0]
            elif len(results) == 0:
                raise ObjectNotFound
            else:
                raise MultipleObjectsReturned


class ModifiableMixin(Common):
    def _process_request_arguments(self, data):
        if data is None:
            data = {}
        return data

    def _execute_request(self, method, data, pk):
        url = (
            self.base_path
            if not pk
            else urljoin(self.base_path, str(pk) + "/")
        )
        return (yield self.yield_request(method=method, path=url, json=data))

    def perform_request(self, method, data=None, pk=False):
        data = self._process_request_arguments(data)
        return (yield from self._execute_request(method, data, pk))

    def create(self, **kwargs):
        return (yield from self.perform_request("POST", data=kwargs))

    def update(self, pk, **kwargs):
        return (yield from self.perform_request("PUT", pk=pk, data=kwargs))

    def partial_update(self, pk, **kwargs):
        return (yield from self.perform_request("PATCH", pk=pk, data=kwargs))

    def delete(self, pk):
        return (yield from self.perform_request("DELETE", pk=pk))


class PageResult(Generic[T], collections.abc.Sequence):
    def __init__(
        self,
        *,
        offset: int,
        limit: int,
        total_count: int,
        results: List[T],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._offset = offset
        self._limit = limit
        self._total_count = total_count
        self._results = results

    @overload
    def __getitem__(self, key: int) -> T:
        ...

    @overload
    def __getitem__(self, key: slice) -> Sequence[T]:
        ...

    def __getitem__(self, key):
        return self._results[key]

    def __len__(self) -> int:
        return len(self._results)

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def total_count(self) -> int:
        return self._total_count
