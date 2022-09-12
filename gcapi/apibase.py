from typing import Any, Dict, Generator, Optional, Type
from urllib.parse import urljoin

from httpx import URL, HTTPStatusError
from httpx._types import URLTypes

from .exceptions import MultipleObjectsReturned, ObjectNotFound
from .sync_async_hybrid_support import (
    CallCapture,
    CapturedCall,
    mark_generator,
)


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
        pass


class Common:
    _client: Optional[ClientInterface] = None
    base_path = ""

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
        return PageResult(
            offset=offset,
            limit=limit,
            total_count=response["count"],
            results=response["results"],
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
            except HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise ObjectNotFound from e
                else:
                    raise e
        else:
            results = yield from self.page(params=params)
            results = list(results)
            if len(results) == 1:
                result = results[0]
            elif len(results) == 0:
                raise ObjectNotFound
            else:
                raise MultipleObjectsReturned

        return result


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


class PageResult(list):
    offset: int
    limit: int
    total_count: int

    def __init__(self, *, offset, limit, total_count, results):
        super().__init__(results)
        self.offset = offset
        self.limit = limit
        self.total_count = total_count
