import collections
from collections.abc import Generator, Iterator, Sequence
from typing import Any, Generic, TypeVar, overload
from urllib.parse import urljoin

from httpx import URL, HTTPStatusError
from httpx._types import URLTypes
from pydantic import RootModel
from pydantic.dataclasses import is_pydantic_dataclass

from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound
from gcapi.sync_async_hybrid_support import (
    CallCapture,
    CapturedCall,
    mark_generator,
)

T = TypeVar("T")


class ClientInterface:
    @property
    def base_url(self) -> URL: ...

    @base_url.setter
    def base_url(self, v: URLTypes): ...

    def validate_url(self, url): ...

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


class PageResult(Generic[T], collections.abc.Sequence):
    def __init__(
        self,
        *,
        offset: int,
        limit: int,
        total_count: int,
        results: list[T],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._offset = offset
        self._limit = limit
        self._total_count = total_count
        self._results = results

    @overload
    def __getitem__(self, key: int) -> T: ...

    @overload
    def __getitem__(self, key: slice) -> Sequence[T]: ...

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


class Common(Generic[T]):
    model: type[T]
    _client: ClientInterface
    base_path: str

    yield_request = CallCapture()


class APIBase(Generic[T], Common[T]):
    sub_apis: dict[str, type["APIBase"]] = {}

    def __init__(self, client) -> None:
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

    def page(
        self, offset=0, limit=100, params=None
    ) -> Generator[T, dict[Any, Any], PageResult[T]]:
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
    def iterate_all(self, params=None) -> Iterator[T]:
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

    def detail(
        self, pk=None, api_url=None, **params
    ) -> Generator[T, dict[Any, Any], T]:
        if sum(bool(arg) for arg in [pk, api_url, params]) != 1:
            raise ValueError(
                "Exactly one of pk, api_url, or params must be specified"
            )
        if pk is not None or api_url is not None:
            if pk is not None:
                request_kwargs = dict(path=urljoin(self.base_path, pk + "/"))
            else:
                request_kwargs = dict(url=api_url)
            try:
                result = yield self.yield_request(
                    method="GET", **request_kwargs
                )
                return self.model(**result)
            except HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise ObjectNotFound from e
                else:
                    raise e
        else:
            results = yield from self.page(params=params)

            if len(results) == 1:
                return results[0]
            elif len(results) == 0:
                raise ObjectNotFound
            else:
                raise MultipleObjectsReturned


class ModifiableMixin(Common):

    response_model: type

    def _process_request_arguments(self, data):
        if data is None:
            return {}
        else:
            return self.recurse_model_dump(data)

    def recurse_model_dump(self, data):
        if isinstance(data, list):
            return [self.recurse_model_dump(v) for v in data]
        elif isinstance(data, dict):
            return {k: self.recurse_model_dump(v) for k, v in data.items()}
        elif is_pydantic_dataclass(type(data)):
            return RootModel[type(data)](data).model_dump()
        else:
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
        result = yield from self.perform_request("POST", data=kwargs)
        return self.response_model(**result)

    def update(self, pk, **kwargs):
        result = yield from self.perform_request("PUT", pk=pk, data=kwargs)
        return self.response_model(**result)

    def partial_update(self, pk, **kwargs):
        result = yield from self.perform_request("PATCH", pk=pk, data=kwargs)
        return self.response_model(**result)

    def delete(self, pk):
        return (yield from self.perform_request("DELETE", pk=pk))
