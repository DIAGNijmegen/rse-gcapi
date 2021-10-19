import logging
import os
import re
from typing import Dict
from urllib.parse import urljoin, urlparse

from httpx import AsyncClient
from httpx import HTTPStatusError, Timeout

logger = logging.getLogger(__name__)


def _generate_auth_header(token: str = "") -> Dict:
    if not token:
        try:
            token = str(os.environ["GRAND_CHALLENGE_AUTHORIZATION"])
        except KeyError:
            raise RuntimeError("Token must be set") from None

    token = re.sub(" +", " ", token)
    token_parts = token.strip().split(" ")

    if len(token_parts) not in [1, 2]:
        raise RuntimeError("Invalid token format")

    return {"Authorization": f"BEARER {token_parts[-1]}"}


class ClientBase(AsyncClient):
    def __init__(
        self,
        token: str = "",
        base_url: str = "https://grand-challenge.org/api/v1/",
        verify: bool = True,
        timeout: float = 60.0,
    ):
        super().__init__(verify=verify, timeout=Timeout(timeout=timeout))

        self.headers.update({"Accept": "application/json"})
        self._auth_header = _generate_auth_header(token=token)

        self._base_url = base_url
        if not self._base_url.startswith("https://"):
            raise RuntimeError("Base URL must be https")

    @property
    def base_url(self):
        return self._base_url

    def validate_url(self, url):
        base = urlparse(self._base_url)
        target = urlparse(url)

        if not target.scheme == "https" or target.netloc != base.netloc:
            raise RuntimeError(f"Invalid target URL: {url}")

    async def __call__(
        self,
        method="GET",
        url="",
        path="",
        params=None,
        json=None,
        extra_headers=None,
        files=None,
        data=None,
    ):
        if not url:
            url = urljoin(self._base_url, path)
        if extra_headers is None:
            extra_headers = {}
        if json is not None:
            extra_headers["Content-Type"] = "application/json"

        self.validate_url(url)

        response = await self.request(
            method=method,
            url=url,
            files={} if files is None else files,
            data={} if data is None else data,
            headers={**self.headers, **self._auth_header, **extra_headers},
            params={} if params is None else params,
            json=json,
        )

        try:
            response.raise_for_status()
        except HTTPStatusError as e:
            if e.response.headers.get("Content-Type") == "application/json":
                message = e.response.json()
                logger.error(f"{method} request to {url} failed: {message}")
            raise

        if response.headers.get("Content-Type") == "application/json":
            return response.json()
        else:
            return response
