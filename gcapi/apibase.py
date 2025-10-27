from __future__ import annotations

import collections
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload
from urllib.parse import urljoin

from httpx import HTTPStatusError
from pydantic import RootModel
from pydantic.dataclasses import is_pydantic_dataclass

from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound

T = TypeVar("T")
RT = TypeVar("RT")

if TYPE_CHECKING:
    from gcapi import Client


class PageResult(Generic[T], collections.abc.Sequence):
    """A paginated result container for API responses.

    This class provides a sequence-like interface for handling paginated API responses,
    containing metadata about the pagination state and the actual results.

    Attributes:
        offset (int): The starting index of the results.
        limit (int): The maximum number of results in this page.
        total_count (int): The total number of items available.
    """

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


class APIBase(Generic[T]):
    model: type[T]
    base_path: str
    sub_apis: dict[str, type[APIBase]] = {}

    def __init__(self, client: Client) -> None:
        self._client = client

        for k, api in list(self.sub_apis.items()):
            setattr(self, k, api(self._client))

    def list(self, params: dict[str, Any] | None = None) -> list[T]:
        """
        Retrieve a raw list of resources from the API endpoint.

        Args:
            params: Query parameters to include in the API request.

        Returns:
            Raw JSON response from the API containing the list of resources.
        """
        result = self._client(method="GET", path=self.base_path, params=params)
        return result

    def page(
        self,
        offset: int = 0,
        limit: int = 100,
        params: dict[str, Any] | None = None,
    ) -> PageResult[T]:
        """
        Retrieve a paginated set of resources from the API endpoint.

        Args:
            offset: The starting index for pagination (zero-based).
            limit: The maximum number of results to return in this page.
            params: Additional query parameters to include in the API request.

        Returns:
            A paginated result containing the requested resources and metadata.
        """
        if params is None:
            params = {}

        params["offset"] = offset
        params["limit"] = limit

        response = self._client(
            method="GET", path=self.base_path, params=params
        )

        results = [self.model(**result) for result in response["results"]]

        return PageResult(
            offset=offset,
            limit=limit,
            total_count=response["count"],
            results=results,
        )

    def iterate_all(self, params: dict[str, Any] | None = None) -> Iterator[T]:
        """
        Iterate through all resources from the API endpoint across all pages.

        This method automatically handles pagination and yields individual resources
        from all pages until all resources have been retrieved.

        Args:
            params: Query parameters to include in the API requests.

        Yields:
            Individual resources from the API endpoint.
        """
        req_count = 100
        offset = 0
        while True:
            current_list = self.page(
                offset=offset,
                limit=req_count,
                params=params,
            )
            if len(current_list) == 0:
                break
            yield from current_list
            offset += req_count

    def detail(
        self,
        pk: str | None = None,
        api_url: str | None = None,
        **params: Any,
    ) -> T:
        """
        Retrieve a specific resource by primary key, URL, or search parameters.

        Args:
            pk: Primary key of the resource to retrieve.
            api_url: Direct API URL of the resource to retrieve.
            **params: Search parameters to find a unique resource, such as `slug="your-slug"`.

        Returns:
            The requested resource instance.

        Raises:
            ValueError: If more than one or none of pk, api_url, or params are specified.
            ObjectNotFound: If no resource is found matching the criteria.
            MultipleObjectsReturned: If multiple resources match the search parameters.
        """
        if sum(bool(arg) for arg in [pk, api_url, params]) != 1:
            raise ValueError(
                "Exactly one of pk, api_url, or params must be specified"
            )
        if pk is not None or api_url is not None:
            if pk is not None:
                request_kwargs = dict(path=urljoin(self.base_path, pk + "/"))
            elif api_url is not None:
                request_kwargs = dict(url=api_url)
            try:
                result = self._client(method="GET", **request_kwargs)
                return self.model(**result)
            except HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise ObjectNotFound from e
                else:
                    raise e
        else:
            results = self.page(params=params)

            if len(results) == 1:
                return results[0]
            elif len(results) == 0:
                raise ObjectNotFound
            else:
                raise MultipleObjectsReturned


class ModifiableMixin(Generic[RT]):
    base_path: str
    _client: Client
    response_model: type[RT]

    def _process_request_arguments(self, data):
        if data is None:
            return {}
        else:
            return self._recurse_model_dump(data)

    def _recurse_model_dump(self, data):
        if isinstance(data, list):
            return [self._recurse_model_dump(v) for v in data]
        elif isinstance(data, dict):
            return {k: self._recurse_model_dump(v) for k, v in data.items()}
        elif is_pydantic_dataclass(type(data)):
            return RootModel[type(data)](data).model_dump()  # type: ignore
        else:
            return data

    def _execute_request(self, method, data, pk):
        url = (
            self.base_path
            if not pk
            else urljoin(self.base_path, str(pk) + "/")
        )
        return self._client(method=method, path=url, json=data)

    def _perform_request(self, method, data=None, pk=False):
        data = self._process_request_arguments(data)
        return self._execute_request(method, data, pk)

    def create(self, **kwargs: Any) -> RT:
        """
        Create a new resource via the API.

        Args:
            **kwargs: Field values for the new resource.

        Returns:
            The created resource instance.
        """
        result = self._perform_request("POST", data=kwargs)
        return self.response_model(**result)

    def update(self, pk: str, **kwargs: Any) -> RT:
        """
        Update an existing resource with a complete replacement.

        Args:
            pk: Primary key of the resource to update.
            **kwargs: Complete field values for the resource update.

        Returns:
            The updated resource instance.
        """
        result = self._perform_request("PUT", pk=pk, data=kwargs)
        return self.response_model(**result)

    def partial_update(self, pk: str, **kwargs: Any) -> RT:
        """
        Partially update an existing resource with only specified fields.

        Args:
            pk: Primary key of the resource to update.
            **kwargs: Partial field values for the resource update.

        Returns:
            The updated resource instance.
        """
        result = self._perform_request("PATCH", pk=pk, data=kwargs)
        return self.response_model(**result)

    def delete(self, pk: str) -> Any:
        """
        Delete a resource from the API.

        Args:
            pk: Primary key of the resource to delete.

        Returns:
            Response from the delete operation.
        """
        return self._perform_request("DELETE", pk=pk)
