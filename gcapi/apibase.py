from typing import Any, Dict, Generator, Optional, Type
from urllib.parse import urljoin

import jsonschema
from httpx import HTTPStatusError, URL
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
    validation_schemas: Optional[Dict[str, jsonschema.Draft7Validator]] = None

    yield_request = CallCapture()


class APIBase(Common):
    sub_apis: Dict[str, Type["APIBase"]] = {}

    def __init__(self, client):
        if self.validation_schemas is None:
            self.validation_schemas = {}

        if isinstance(self, ModifiableMixin):
            ModifiableMixin.__init__(self)

        self._client = client

        for k, api in list(self.sub_apis.items()):
            setattr(self, k, api(self._client))

    def verify_against_schema(self, value):
        """
        Verify the given value against the configured jsonschema.

        Parameters
        ----------
        value: Any
            Some parsed json-value to verify.

        Raises
        ------
        ValidationError:
            Raised in case the value verification failed.
        """
        schema = self.validation_schemas.get("GET")
        if schema is not None:
            schema.validate(value)

    def list(self, params=None):
        result = yield self.yield_request(
            method="GET", path=self.base_path, params=params
        )
        for i in result:
            self.verify_against_schema(i)
        return result

    def page(self, offset=0, limit=100, params=None):
        if params is None:
            params = {}
        params["offset"] = offset
        params["limit"] = limit
        result = (
            yield self.yield_request(
                method="GET", path=self.base_path, params=params
            )
        )["results"]
        for i in result:
            self.verify_against_schema(i)
        return result

    @mark_generator
    def iterate_all(self, params=None):
        req_count = 100
        offset = 0
        while True:
            current_list = yield from self.page(
                offset=offset, limit=req_count, params=params
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

            self.verify_against_schema(result)
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
    def _process_request_arguments(self, method, data):
        if data is None:
            data = {}
        schema = self.validation_schemas.get(method)
        if schema:
            schema.validate(data)
        return data

    def _execute_request(self, method, data, pk):
        url = (
            self.base_path
            if not pk
            else urljoin(self.base_path, str(pk) + "/")
        )
        return (yield self.yield_request(method=method, path=url, json=data))

    def perform_request(self, method, data=None, pk=False):
        data = self._process_request_arguments(method, data)
        return (yield from self._execute_request(method, data, pk))

    def create(self, **kwargs):
        return (yield from self.perform_request("POST", data=kwargs))

    def update(self, pk, **kwargs):
        return (yield from self.perform_request("PUT", pk=pk, data=kwargs))

    def partial_update(self, pk, **kwargs):
        return (yield from self.perform_request("PATCH", pk=pk, data=kwargs))

    def delete(self, pk):
        return (yield from self.perform_request("DELETE", pk=pk))
