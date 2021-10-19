from typing import Dict, Optional, Type
from urllib.parse import urljoin

import jsonschema
from httpx import HTTPStatusError

from gcapi.client import ClientBase
from .exceptions import MultipleObjectsReturned, ObjectNotFound


class APIBase:
    _client: Optional[ClientBase] = None
    base_path = ""
    sub_apis: Dict[str, Type["APIBase"]] = {}

    validation_schemas = None  # type: Dict[str, jsonschema.Draft7Validator]

    def __init__(self, client):
        if self.validation_schemas is None:
            self.validation_schemas = {}

        if isinstance(self, ModifiableMixin):
            ModifiableMixin.__init__(self)

        self._client = client

        for k, api in list(self.sub_apis.items()):
            setattr(self, k, api(self._client))

    def _verify_against_schema(self, value):
        schema = self.validation_schemas.get("GET")
        if schema is not None:
            schema.validate(value)

    def list(self, params=None):
        result = self._client(method="GET", path=self.base_path, params=params)
        for i in result:
            self._verify_against_schema(i)
        return result

    def page(self, offset=0, limit=100, params=None):
        if params is None:
            params = {}
        params["offset"] = offset
        params["limit"] = limit
        result = self._client(
            method="GET", path=self.base_path, params=params
        )["results"]
        for i in result:
            self._verify_against_schema(i)
        return result

    def iterate_all(self, params=None):
        req_count = 100
        offset = 0
        while True:
            current_list = self.page(
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
                result = self._client(
                    method="GET", path=urljoin(self.base_path, pk + "/")
                )
            except HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise ObjectNotFound from e
                else:
                    raise e

            self._verify_against_schema(result)
        else:
            results = list(self.page(params=params))
            if len(results) == 1:
                result = results[0]
            elif len(results) == 0:
                raise ObjectNotFound
            else:
                raise MultipleObjectsReturned

        return result


class ModifiableMixin:
    _client: Optional[ClientBase] = None

    def __init__(self):
        pass

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
        return self._client(method=method, path=url, json=data)

    def perform_request(self, method, data=None, pk=False):
        data = self._process_request_arguments(method, data)
        return self._execute_request(method, data, pk)

    def create(self, **kwargs):
        return self.perform_request("POST", data=kwargs)

    def update(self, pk, **kwargs):
        return self.perform_request("PUT", pk=pk, data=kwargs)

    def partial_update(self, pk, **kwargs):
        return self.perform_request("PATCH", pk=pk, data=kwargs)

    def delete(self, pk):
        return self.perform_request("DELETE", pk=pk)
