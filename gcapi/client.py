import logging
import os
import re
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

from httpx import Client as SyncClient, AsyncClient
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


class ClientBase(SyncClient):
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

    def _validate_url(self, url):
        base = urlparse(self._base_url)
        target = urlparse(url)

        if not target.scheme == "https" or target.netloc != base.netloc:
            raise RuntimeError(f"Invalid target URL: {url}")

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
    ):
        if not url:
            url = urljoin(self._base_url, path)
        if extra_headers is None:
            extra_headers = {}
        if json is not None:
            extra_headers["Content-Type"] = "application/json"

        self._validate_url(url)

        response = self.request(
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

    def _upload_files(self, *, files, **kwargs):
        uploads = []
        for file in files:
            with open(file, "rb") as f:
                uploads.append(
                    self.uploads.upload_fileobj(fileobj=f, filename=file.name)
                )

        raw_image_upload_session = self.raw_image_upload_sessions.create(
            uploads=[u["api_url"] for u in uploads], **kwargs,
        )

        return raw_image_upload_session

    def run_external_job(self, *, algorithm: str, inputs: Dict[str, Any]):
        """
        Starts an algorithm job with the provided inputs.

        You will need to provide the slug of the algorithm. You can find this in the
        url of the algorithm that you want to use. For instance, if you want to use
        the algorithm at

            https://grand-challenge.org/algorithms/corads-ai/

        the slug for this algorithm is "corads-ai".

        For each input interface defined on the algorithm you need to provide a
        key-value pair (unless the interface has a default value),
        the key being the slug of the interface, the value being the
        value for the interface. You can get the interfaces of an algorithm by calling

            client.algorithms.detail(slug="corads-ai")

        and inspecting the ["inputs"] of the result.

        For image type interfaces (super_kind="Image"), you can provide a list of
        files, which will be uploaded, or a link to an existing image.

        So to run this algorithm with a new upload you would call this function by:

            client.run_external_job(
                algorithm="corads-ai",
                inputs={
                    "generic-medical-image": [...]
                }
            )

        or to run with an existing image by:
            client.run_external_job(
                algorithm="corads-ai",
                inputs={
                    "generic-medical-image":
                    "https://grand-challenge.org/api/v1/cases/images/.../"
                }
            )

        Parameters
        ----------
        algorithm
        inputs

        Returns
        -------
        The created job
        """
        alg = self.algorithms.detail(slug=algorithm)
        input_interfaces = {ci["slug"]: ci for ci in alg["inputs"]}

        for ci in input_interfaces:
            if (
                ci not in inputs
                and input_interfaces[ci]["default_value"] is None
            ):
                raise ValueError(f"{ci} is not provided")

        job = {"algorithm": alg["api_url"], "inputs": []}
        for input_title, value in inputs.items():
            ci = input_interfaces.get(input_title, None)
            if not ci:
                raise ValueError(
                    f"{input_title} is not an input interface for this algorithm"
                )

            i = {"interface": ci["slug"]}
            if ci["super_kind"].lower() == "image":
                if isinstance(value, list):
                    raw_image_upload_session = self._upload_files(files=value)
                    i["upload_session"] = raw_image_upload_session["api_url"]
                elif isinstance(value, str):
                    i["image"] = value
            else:
                i["value"] = value
            job["inputs"].append(i)

        return self.algorithm_jobs.create(**job)

    def upload_cases(
        self,
        *,
        files: List[str],
        archive: str = None,
        reader_study: str = None,
    ):
        """
        Uploads a set of files to an archive or reader study.

        A new upload session will be created on grand challenge to import and
        standardise your files. This function will return this new upload
        session object, that you can query for the import status. If this
        import is successful, the new images will then be added to the selected
        archive or reader study.

        You will need to provide the slugs of the objects to pass the images
        along to. You can find this in the url of the object that you want
        to use. For instance, if you want to use the archive at

            https://grand-challenge.org/archives/corads-ai/

        the slug for this is "corads-ai", so you would call this function with

            upload_cases(files=[...], archive="corads-ai")

        Parameters
        ----------
        files
            The list of files on disk that form 1 Image. These can be a set of
            .mha, .mhd, .raw, .zraw, .dcm, .nii, .nii.gz, .tiff, .png, .jpeg,
            .jpg, .svs, .vms, .vmu, .ndpi, .scn, .mrxs and/or .bif files.
        archive
            The slug of the archive to use.
        reader_study
            The slug of the reader study to use.

        Returns
        -------
            The created upload session.
        """
        upload_session_data = {}

        if len(files) == 0:
            raise ValueError("You must specify the files to upload")

        if reader_study is not None:
            upload_session_data["reader_study"] = reader_study

        if archive is not None:
            upload_session_data["archive"] = archive

        if len(upload_session_data) != 1:
            raise ValueError("One of archive or reader_study should be set")

        raw_image_upload_session = self._upload_files(
            files=files, **upload_session_data
        )

        return raw_image_upload_session
