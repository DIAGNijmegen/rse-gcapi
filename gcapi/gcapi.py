# -*- coding: utf-8 -*-
try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin

from requests import Session


class APIBase:
    base_path = ""

    def __init__(self, client):
        self._client = client

    def list(self):
        return self._client(method="GET", path=self.base_path)

    def detail(self, pk):
        return self._client(method="GET", path=urljoin(self.base_path, pk))


class ImagesAPI(APIBase):
    base_path = "cases/images"

    def list(self):
        # TODO
        raise NotImplementedError


class WorkstationSessionsAPI(APIBase):
    base_path = "workstations/sessions"


class Client(Session):
    def __init__(
        self, token=None, base_url="https://grand-challenge.org/api/v1/", verify=True
    ):
        super(Client, self).__init__()

        self.headers.update({"Accept": "application/json"})

        if token:
            self.headers.update({"Authorization": "TOKEN {}".format(token)})
        else:
            raise RuntimeError("Token must be set")

        self._base_url = base_url
        if not self._base_url.startswith("https://"):
            raise RuntimeError("Base URL must be https")

        # Should we verify the servers SSL certificates?
        self._verify = verify

        self.images = ImagesAPI(client=self)
        self.sessions = WorkstationSessionsAPI(client=self)

    def __call__(self, method="GET", path=""):
        response = self.request(
            method=method,
            url=urljoin(self._base_url, path),
            headers=self.headers,
            verify=self._verify,
        )

        response.raise_for_status()

        return response.json()
