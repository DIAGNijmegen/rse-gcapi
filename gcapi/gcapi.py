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

    def list(self, offset=0, limit=100):
        return self._client(
            method="GET", path=self.base_path, params={"offset": offset, "limit": limit}
        )

    def detail(self, pk):
        return self._client(method="GET", path=urljoin(self.base_path, pk + "/"))


class ImagesAPI(APIBase):
    base_path = "cases/images/"


class ReaderStudiesAPI(APIBase):
    base_path = "reader-studies/"


class WorkstationSessionsAPI(APIBase):
    base_path = "workstations/sessions/"


class AlgorithmsAPI(APIBase):
    base_path = "algorithms/"


class AlgorithmResultsAPI(APIBase):
    base_path = "algorithms/results/"


class AlgorithmJobsAPI(APIBase):
    base_path = "algorithms/jobs/"


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
        self.reader_studies = ReaderStudiesAPI(client=self)
        self.sessions = WorkstationSessionsAPI(client=self)
        self.algorithms = AlgorithmsAPI(client=self)
        self.algorithm_results = AlgorithmResultsAPI(client=self)
        self.algorithm_jobs = AlgorithmJobsAPI(client=self)

    def _validate_url(self, url):
        if not url.startswith(self._base_url):
            raise RuntimeError("{} does not start with {}".format(url, self._base_url))

    def __call__(self, method="GET", url="", path="", params=None):
        if not url:
            url = urljoin(self._base_url, path)

        self._validate_url(url)

        response = self.request(
            method=method,
            url=url,
            headers=self.headers,
            verify=self._verify,
            params={} if params is None else params,
        )

        response.raise_for_status()

        return response.json()
