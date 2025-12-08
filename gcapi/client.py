import json
import logging
import os
import re
import sys
import uuid
from asyncio import Semaphore
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack
from pathlib import Path
from random import randint
from time import sleep
from typing import Any, cast, get_type_hints
from urllib.parse import urljoin

import httpx
from asgiref.sync import async_to_sync, sync_to_async
from httpx import URL, HTTPStatusError, Timeout

if sys.version_info >= (3, 11):
    from asyncio import TaskGroup
else:  # Use backport for Python <3.11
    from taskgroup import TaskGroup

import gcapi.models
from gcapi.apibase import APIBase, ModifiableMixin
from gcapi.check_version import check_version
from gcapi.create_strategies import (
    JobInputsCreateStrategy,
    SocketValueCreateStrategy,
    SocketValueSpec,
    select_socket_value_strategy,
)
from gcapi.exceptions import ObjectNotFound, SocketNotFound
from gcapi.retries import BaseRetryStrategy, SelectiveBackoffStrategy
from gcapi.transports import RetryTransport
from gcapi.typing import ReadableBuffer, SocketValuePostSet, Unset, UnsetType

logger = logging.getLogger(__name__)


def is_uuid(s: str) -> bool:
    """
    Check if a string is a valid UUID.

    Args:
        s: The string to check for UUID validity.

    Returns:
        True if the string is a valid UUID, False otherwise.
    """
    try:
        uuid.UUID(s)
    except ValueError:
        return False
    else:
        return True


class ImagesAPI(APIBase[gcapi.models.HyperlinkedImage]):
    base_path = "cases/images/"
    model = gcapi.models.HyperlinkedImage

    def download(
        self,
        *,
        output_directory: str | Path,
        filename: str | None = None,
        image_type: str | None = None,
        pk: str | None = None,
        url: str | None = None,
        files: list | None = None,
        **params: Any,
    ) -> list[Path]:
        """
        Download image files to local filesystem.

        Args:
            output_directory: Directory to save downloaded files.
            filename: Optional, base filename for downloaded files. Extension is added automatically.
            image_type: Restrict download to a particular image type.
            pk: Primary key of the image to download.
            url: API URL of the image to download.
            files: List of file objects to download directly.
            **params: Additional parameters for image detail lookup.

        Returns:
            List of Path objects for downloaded files.

        Raises:
            ValueError: If not exactly one of pk, url, files, or params is specified.
        """
        if len([p for p in (pk, url, files, params) if p]) != 1:
            raise ValueError(
                "Exactly one of pk, url, files or params must be specified"
            )

        # Retrieve details of the image if needed
        if files is None:
            if pk is not None:
                image = self.detail(pk=pk)
            elif url is not None:
                image = self.detail(api_url=url)
            else:
                image = self.detail(**params)

            if image.dicom_image_set is not None:
                if filename is not None:
                    raise ValueError(
                        "Do not provide a filename for DICOM image sets"
                    )

                return self._download_dicom_image_set(
                    pk=image.pk,
                    output_directory=output_directory,
                )

            filename = filename or image.pk
            files = image.files

        # Make sure destination exists
        output_directory = Path(output_directory).absolute()
        output_directory.mkdir(parents=True, exist_ok=True)

        filename = filename or "image"

        # Download the files
        downloaded_files = []
        for file in files:
            if image_type and file.image_type != image_type:
                continue

            data = self._client(
                method="GET", url=file.file, follow_redirects=True
            ).content

            suffix = file.file.split(".")[-1]
            local_file = output_directory / f"{filename}.{suffix}"

            if local_file.exists():
                raise FileExistsError(f"File {local_file} already exists")

            with local_file.open("wb") as fp:
                fp.write(data)

            downloaded_files.append(local_file)

        return downloaded_files

    @async_to_sync
    async def _download_dicom_image_set(
        self,
        *,
        pk: str,
        output_directory: Path | str,
    ) -> list[Path]:
        """
        Download all DICOM instances of a DICOM image set.

        Args:
            pk: Primary key of the image to download.
            output_directory: Directory to save downloaded files.
            filename: Optional prefix filename for downloaded files.

        Returns:
            List of Path objects for downloaded DICOM files.
        """
        resp = self._client(
            path=f"cases/images/{pk}/dicom/instances/",
            method="GET",
        )

        output = Path(output_directory).absolute()
        output.mkdir(parents=True, exist_ok=True)

        semaphore = Semaphore(self._client.max_concurrent_downloads)

        async def download_with_semaphore(instance):
            sop_instance_uid = instance["sop_instance_uid"]
            output_file = output / f"{sop_instance_uid}.dcm"

            if output_file.exists():
                raise FileExistsError(f"File {output_file} already exists")

            async with semaphore:
                return await self._download_dicom_instance(
                    stream_kwargs=instance["get_instance"],
                    file=output_file,
                )

        tasks = []
        async with TaskGroup() as tg:
            for instance in resp["instances"]:
                task = tg.create_task(download_with_semaphore(instance))
                tasks.append(task)

        return [t.result() for t in tasks]

    @sync_to_async(thread_sensitive=False)
    def _download_dicom_instance(
        self, stream_kwargs: dict[str, Any], file: Path
    ):

        with open(file, "wb") as f:
            with httpx.stream(
                **stream_kwargs,
            ) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        return file


class UploadSessionsAPI(
    APIBase[gcapi.models.RawImageUploadSession],
):
    base_path = "cases/upload-sessions/"
    model = gcapi.models.RawImageUploadSession
    response_model = gcapi.models.RawImageUploadSession


class WorkstationSessionsAPI(APIBase[gcapi.models.Session]):
    base_path = "workstations/sessions/"
    model = gcapi.models.Session
    response_model = gcapi.models.RawImageUploadSession


class ReaderStudyQuestionsAPI(APIBase[gcapi.models.Question]):
    base_path = "reader-studies/questions/"
    model = gcapi.models.Question


class ReaderStudyMineAnswersAPI(
    ModifiableMixin[gcapi.models.Answer],
    APIBase[gcapi.models.Answer],
):
    base_path = "reader-studies/answers/mine/"
    model = gcapi.models.Answer
    response_model = gcapi.models.Answer


class ReaderStudyAnswersAPI(
    ModifiableMixin[gcapi.models.Answer],
    APIBase[gcapi.models.Answer],
):
    base_path = "reader-studies/answers/"
    model = gcapi.models.Answer
    response_model = gcapi.models.Answer

    sub_apis = {"mine": ReaderStudyMineAnswersAPI}

    mine = None  # type: ReaderStudyMineAnswersAPI

    def _process_request_arguments(self, data):
        if data is not None:
            key_and_url = {
                "question": ReaderStudyQuestionsAPI.base_path,
                "display_set": ReaderStudyDisplaySetsAPI.base_path,
            }
            for key, api in key_and_url.items():
                if is_uuid(data.get(key, "")):
                    data[key] = str(
                        self._client.base_url.join(api).join(data[key] + "/")
                    )

        return super()._process_request_arguments(data)


class ReaderStudyDisplaySetsAPI(
    ModifiableMixin[gcapi.models.DisplaySetPost],
    APIBase[gcapi.models.DisplaySet],
):
    base_path = "reader-studies/display-sets/"
    model = gcapi.models.DisplaySet
    response_model = gcapi.models.DisplaySetPost


class ReaderStudiesAPI(APIBase[gcapi.models.ReaderStudy]):
    base_path = "reader-studies/"
    model = gcapi.models.ReaderStudy

    sub_apis = {
        "answers": ReaderStudyAnswersAPI,
        "questions": ReaderStudyQuestionsAPI,
        "display_sets": ReaderStudyDisplaySetsAPI,
    }

    answers = None  # type: ReaderStudyAnswersAPI
    questions = None  # type: ReaderStudyQuestionsAPI
    display_sets = None  # type: ReaderStudyDisplaySetsAPI

    def ground_truth(self, pk: str, case_pk: str) -> dict:
        """
        Get ground truth data for a specific case in a reader study.

        Args:
            pk: Primary key of the reader study.
            case_pk: Primary key of the case.

        Returns:
            Ground truth data for the specified case.
        """
        return self._client(
            method="GET",
            path=urljoin(
                self.base_path, pk + "/ground-truth/" + case_pk + "/"
            ),
        )


class AlgorithmsAPI(APIBase[gcapi.models.Algorithm]):
    base_path = "algorithms/"
    model = gcapi.models.Algorithm


class AlgorithmJobsAPI(
    ModifiableMixin[gcapi.models.JobPost],
    APIBase[gcapi.models.HyperlinkedJob],
):
    base_path = "algorithms/jobs/"
    model = gcapi.models.HyperlinkedJob
    response_model = gcapi.models.JobPost

    def by_input_image(self, pk: str) -> Iterator[gcapi.models.HyperlinkedJob]:
        """
        Get algorithm jobs filtered by input image.

        Args:
            pk: Primary key of the input image to filter jobs by.

        Yields:
            Algorithm job instances that use the specified input image.
        """
        yield from self.iterate_all(params={"image": pk})


class AlgorithmImagesAPI(APIBase[gcapi.models.AlgorithmImage]):
    base_path = "algorithms/images/"
    model = gcapi.models.AlgorithmImage


class ArchivesAPI(APIBase[gcapi.models.Archive]):
    base_path = "archives/"
    model = gcapi.models.Archive


class ArchiveItemsAPI(
    ModifiableMixin[gcapi.models.ArchiveItemPost],
    APIBase[gcapi.models.ArchiveItem],
):
    base_path = "archives/items/"
    model = gcapi.models.ArchiveItem
    response_model = gcapi.models.ArchiveItemPost


class ComponentInterfacesAPI(APIBase[gcapi.models.ComponentInterface]):
    base_path = "components/interfaces/"
    model = gcapi.models.ComponentInterface


class UploadsAPI(APIBase[gcapi.models.UserUpload]):
    base_path = "uploads/"
    model = gcapi.models.UserUpload

    chunk_size = 32 * 1024 * 1024
    n_presigned_urls = 5  # number of pre-signed urls to generate
    max_retries = 10

    def create(self, *, filename: str | Path) -> gcapi.models.UserUpload:
        """
        Create a new upload session.

        Args:
            filename: Name of the file to be uploaded.

        Returns:
            The created upload session model instance.
        """
        result = self._client(
            method="POST",
            path=self.base_path,
            json={"filename": str(filename)},
        )
        return self.model(**result)

    def generate_presigned_urls(
        self, *, pk: str, s3_upload_id: str, part_numbers: list[int]
    ) -> gcapi.models.UserUploadPresignedURLs:
        """
        Generate presigned URLs for multipart upload parts.

        Args:
            pk: Primary key of the upload session.
            s3_upload_id: S3 multipart upload identifier.
            part_numbers: List of part numbers to generate URLs for.
        """
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/generate-presigned-urls/"
        )
        result = self._client(
            method="PATCH", path=url, json={"part_numbers": part_numbers}
        )
        return gcapi.models.UserUploadPresignedURLs(**result)

    def abort_multipart_upload(
        self, *, pk: str, s3_upload_id: str
    ) -> gcapi.models.UserUpload:
        """
        Abort a multipart upload session.

        Args:
            pk: Primary key of the upload session.
            s3_upload_id: S3 multipart upload identifier to abort.

        Returns:
            Patched upload after aborting the multipart upload.
        """
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/abort-multipart-upload/"
        )
        result = self._client(method="PATCH", path=url)
        return gcapi.models.UserUpload(**result)

    def complete_multipart_upload(
        self, *, pk: str, s3_upload_id: str, parts: list
    ) -> gcapi.models.UserUploadComplete:
        """
        Complete a multipart upload session.

        Args:
            pk: Primary key of the upload session.
            s3_upload_id: S3 multipart upload identifier.
            parts: List of completed parts with ETag and PartNumber.

        Returns:
            Patched upload after completing the multipart upload.
        """
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/complete-multipart-upload/"
        )
        result = self._client(method="PATCH", path=url, json={"parts": parts})
        return gcapi.models.UserUploadComplete(**result)

    def list_parts(
        self, *, pk: str, s3_upload_id: str
    ) -> gcapi.models.UserUploadParts:
        """
        List parts of a multipart upload.

        Args:
            pk: Primary key of the upload session.
            s3_upload_id: S3 multipart upload identifier.

        Returns:
            list of uploaded parts.
        """
        url = urljoin(self.base_path, f"{pk}/{s3_upload_id}/list-parts/")
        result = self._client(path=url)
        return gcapi.models.UserUploadParts(**result)

    @async_to_sync
    async def upload_multiple_fileobj(
        self,
        *,
        file_objects: Sequence[ReadableBuffer],
        filenames: Sequence[str],
    ) -> list[gcapi.models.UserUpload]:
        """
        Upload multiple files concurrently.

        Args:
            file_objects: List of file objects to upload.
            filenames: List of filenames corresponding to the file objects.

        Returns:
            List of completed upload model instances.
        """
        semaphore = Semaphore(  # Limit concurrent uploads
            self._client.max_concurrent_uploads
        )

        upload_fileobj_async = sync_to_async(
            self.upload_fileobj,
            thread_sensitive=False,
        )

        async def upload(fileobj, filename):
            async with semaphore:
                return await upload_fileobj_async(
                    fileobj=fileobj, filename=filename
                )

        tasks = []
        async with TaskGroup() as tg:
            for fileobj, filename in zip(file_objects, filenames, strict=True):
                task = tg.create_task(upload(fileobj, filename))
                tasks.append(task)

        return [t.result() for t in tasks]

    def upload_fileobj(
        self,
        *,
        fileobj: ReadableBuffer,
        filename: str,
    ) -> gcapi.models.UserUploadComplete:
        """
        Upload a file object using multipart upload.

        Args:
            fileobj: File object to upload
            filename: Name of the file being uploaded.

        Returns:
            gcapi.models.UserUpload: The completed upload model instance.

        Raises:
            Exception: If upload fails, the multipart upload is aborted and exception is re-raised.
        """
        user_upload = self.create(filename=filename)

        pk = user_upload.pk
        s3_upload_id = user_upload.s3_upload_id

        try:
            parts = self._put_fileobj(
                fileobj=fileobj, pk=pk, s3_upload_id=s3_upload_id
            )
        except Exception:
            self.abort_multipart_upload(pk=pk, s3_upload_id=s3_upload_id)
            raise

        return self.complete_multipart_upload(
            pk=pk, s3_upload_id=s3_upload_id, parts=parts
        )

    def _put_fileobj(
        self,
        *,
        fileobj: ReadableBuffer,
        pk: str,
        s3_upload_id: str,
    ) -> list[dict]:
        part_number = 1  # s3 uses 1-indexed chunks
        presigned_urls = {}
        parts = []

        while True:
            chunk = fileobj.read(self.chunk_size)

            if not chunk:
                break

            if str(part_number) not in presigned_urls:
                presigned_urls.update(
                    self._get_next_presigned_urls(
                        pk=pk,
                        s3_upload_id=s3_upload_id,
                        part_number=part_number,
                    )
                )

            response = self._put_chunk(
                chunk=chunk, url=presigned_urls[str(part_number)]
            )

            parts.append(
                {"ETag": response.headers["ETag"], "PartNumber": part_number}
            )

            part_number += 1

        return parts

    def _get_next_presigned_urls(
        self, *, pk, s3_upload_id, part_number
    ) -> dict[str, str]:
        response = self.generate_presigned_urls(
            pk=pk,
            s3_upload_id=s3_upload_id,
            part_numbers=[
                *range(part_number, part_number + self.n_presigned_urls)
            ],
        )
        return response.presigned_urls

    def _put_chunk(self, *, chunk: bytes, url: str) -> httpx.Response:
        num_retries = 0
        e = Exception()

        while num_retries < self.max_retries:
            try:
                result = self._client.request(
                    method="PUT", url=url, content=chunk
                )
                break
            except HTTPStatusError as _e:
                status_code = _e.response.status_code
                if status_code in [409, 423] or status_code >= 500:
                    num_retries += 1
                    e = _e
                    sleep((2**num_retries) + (randint(0, 1000) / 1000))
                else:
                    raise
        else:
            raise e

        return result


class WorkstationConfigsAPI(APIBase[gcapi.models.WorkstationConfig]):
    base_path = "workstations/configs/"
    model = gcapi.models.WorkstationConfig


def _generate_auth_header(token: str = "") -> dict:
    """
    Generate authorization header for API requests.

    Args:
        token (str, optional): Authorization token. If empty, retrieves token from
        GRAND_CHALLENGE_AUTHORIZATION environment variable.

    Returns:
        dict: Dictionary containing the Authorization header.

    Raises:
        RuntimeError: If no token is provided and GRAND_CHALLENGE_AUTHORIZATION
        environment variable is not set, or if token format is invalid.
    """
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


class ApiDefinitions:
    images: ImagesAPI
    reader_studies: ReaderStudiesAPI
    sessions: WorkstationSessionsAPI
    uploads: UploadsAPI
    algorithms: AlgorithmsAPI
    algorithm_jobs: AlgorithmJobsAPI
    algorithm_images: AlgorithmImagesAPI
    archives: ArchivesAPI
    workstation_configs: WorkstationConfigsAPI
    raw_image_upload_sessions: UploadSessionsAPI
    archive_items: ArchiveItemsAPI
    interfaces: ComponentInterfacesAPI


class Client(httpx.Client, ApiDefinitions):
    """The Grand Challenge API client."""

    _api_meta: ApiDefinitions

    def __init__(
        self,
        token: str = "",
        base_url: str = "https://grand-challenge.org/api/v1/",
        verify: bool = True,
        timeout: float = 60.0,
        retry_strategy: Callable[[], BaseRetryStrategy] | None = None,
        max_concurrent_uploads: int = 10,
        max_concurrent_downloads: int = 10,
    ):
        """
        Args:
            token: Authorization token for API access. If not provided, will be read
                from GRAND_CHALLENGE_AUTHORIZATION environment variable.
            base_url: Base URL for the API.
            verify: Whether to verify SSL certificates.
            timeout: Request timeout in seconds.
            retry_strategy: Factory function that returns a retry strategy instance. If None,
                uses SelectiveBackoffStrategy with default parameters.
            max_concurrent_uploads: Maximum number of concurrent uploads allowed.
            max_concurrent_downloads: Maximum number of concurrent downloads allowed.
        """
        check_version(base_url=base_url)

        retry_strategy = retry_strategy or SelectiveBackoffStrategy(
            backoff_factor=0.1,
            maximum_number_of_retries=8,  # ~25.5 seconds total backoff
        )
        httpx.Client.__init__(
            self,
            verify=verify,
            timeout=Timeout(timeout=timeout),
            transport=RetryTransport(
                verify=verify,
                retry_strategy=retry_strategy,
            ),
        )

        self.headers.update({"Accept": "application/json"})
        self._auth_header = _generate_auth_header(token=token)

        self.base_url = URL(base_url)
        if self.base_url.scheme.lower() != "https":
            raise RuntimeError("Base URL must be https")

        self.max_concurrent_uploads = max_concurrent_uploads
        self.max_concurrent_downloads = max_concurrent_downloads

        self._api_meta = ApiDefinitions()
        for name, cls in get_type_hints(ApiDefinitions).items():
            setattr(self._api_meta, name, cls(client=self))

        self._socket_cache: dict[str, gcapi.models.ComponentInterface] = {}
        self._algorithm_cache: dict[str, gcapi.models.Algorithm] = {}
        self._archive_cache: dict[str, gcapi.models.Archive] = {}

    def __getattr__(self, item):
        api = getattr(self._api_meta, item, None)
        if api:
            return api
        else:
            raise AttributeError(f"Client has no function or API {item!r}")

    def _validate_url(self, url):
        url = URL(url)

        if not url.scheme == "https" or url.netloc != self.base_url.netloc:
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
        follow_redirects=False,
    ) -> Any:
        """
        Make an HTTP request to the API.

        Args:
            method (str, optional): HTTP method to use, by default "GET".
            url (str, optional): Full URL to request. If provided, path is ignored.
            path (str, optional): Path relative to base_url. Ignored if url is provided.
            params (dict, optional): Query parameters to include in the request.
            json (dict, optional): JSON data to send in the request body.
            extra_headers (dict, optional): Additional headers to include in the request.
            files (dict, optional): Files to upload with the request.
            data (dict, optional): Form data to send in the request body.
            follow_redirects (bool, optional): Whether to follow HTTP redirects, by default False.

        Returns:
            Any: JSON response data if Content-Type is application/json,
                otherwise the raw response object.

        Raises:
            HTTPStatusError: If the HTTP request fails with a non-2xx status code.
        """
        if url:
            url = URL(url)
        else:
            url = self.base_url.join(path)
        if extra_headers is None:
            extra_headers = {}
        if json is not None:
            extra_headers["Content-Type"] = "application/json"

        self._validate_url(url)

        response = self.request(
            method=method,
            url=str(url),
            files={} if files is None else files,
            data={} if data is None else data,
            headers={
                **self.headers,
                **self._auth_header,
                **extra_headers,
            },
            params={} if params is None else params,
            json=json,
            follow_redirects=follow_redirects,
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

    def _fetch_algorithm_detail(self, slug: str) -> gcapi.models.Algorithm:
        if slug not in self._algorithm_cache:
            self._algorithm_cache[slug] = self.algorithms.detail(slug=slug)
        return self._algorithm_cache[slug]

    def download_socket_value(
        self,
        value: gcapi.models.HyperlinkedComponentInterfaceValue,
        *,
        output_directory: Path,
    ):
        """Download a socket value to the specified output directory.

        Uses the socket's relative path to determine the filename. The relative
        path is fixed and unique per socket, so downloading multiple different values
        will not overwrite each other.

        In addition, if the file to be downloaded already exists in the output
        directory, a FileExistsError is raised to prevent overwriting existing files.

        Args:
            value: The socket value to download.
            output_directory: The directory to download the value into.
        """

        target_path = output_directory / value.interface.relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        super_kind = value.interface.super_kind.casefold()
        if super_kind == "image":
            # Image values
            self.images.download(
                url=str(value.image),
                output_directory=target_path,
            )
        elif super_kind == "value":
            if target_path.exists():
                raise FileExistsError(f"File {target_path} already exists")
            # Direct values (e.g. '42')
            with open(target_path, "w") as f:
                json.dump(value.value, f, indent=2)
        elif super_kind == "file":
            if target_path.exists():
                raise FileExistsError(f"File {target_path} already exists")
            # Values stored as files
            resp = self(
                url=str(value.file),
                follow_redirects=True,
            )
            content = (
                resp.content
                if isinstance(resp, httpx.Response)
                else json.dumps(resp).encode()
            )
            with open(target_path, "wb") as f:
                f.write(content)
        else:
            raise ValueError(
                f"Unexpected super_kind {value.interface.super_kind}"
            )

    def start_algorithm_job(
        self,
        *,
        algorithm_slug: str,
        inputs: list[SocketValueSpec],
    ) -> gcapi.models.JobPost:
        """
        Starts an algorithm job with the provided inputs.

        ??? tip "Getting the interfaces of an algorithm"
            You can get the interfaces (i.e. all possible socket sets) of
            an algorithm by calling, and inspecting the .interface of the
            result of:

            ```Python
            client.algorithms.detail(slug="corads-ai")
            ```

        ??? tip "Re-using existing images"
            Existing images on Grand Challenge can be re-used by either
            passing an API url, or an existing socket value:

            ```Python
            from gcapi import SocketValueSpec

            image = client.images.detail(pk="ad5...")
            ds = client.reader_studies.display_sets.detail(pk="f5...")
            socket_value = ds.values[0]

            inputs = [
                SocketValueSpec(socket_slug="slug-0", existing_image_api_url=image.api_url),
                SocketValueSpec(socket_slug="slug-1", existing_socket_value=socket_value),
                SocketValueSpec(socket_slug="slug-2", existing_image_api_url=socket_value.image),
            ]
            ```

        ??? tip "Re-using existing socket values"
            Existing socket values from other display sets can be re-used by
            passing a socket value. The sockets must be the same.

            For instance:

            ```Python
            from gcapi import SocketValueSpec

            ds = client.reader_studies.display_sets.detail(pk="f5...")
            inputs = [
                SocketValueSpec(socket_slug="slug-0", existing_socket_value=ds.values[0]),
                SocketValueSpec(socket_slug="slug-1", existing_socket_value=ds.values[1]),
            ]
            ```

        Args:
            algorithm_slug: Slug for the algorithm (e.g. `"corads-ai"`).
                You can find this readily in the URL you use to visit the algorithm page:
                `https://grand-challenge.org/algorithms/corads-ai/`

            inputs: A list of socket value specifications.
                Each specification defines a socket slug and exactly one source
                (`value`, `file`, `files`, `existing_image_api_url`, or
                `existing_socket_value`).

        Returns:
            The newly created Job (post) object. Note that not all inputs will
                be immediately available until the background processing has
                completed.
        """

        algorithm = self._fetch_algorithm_detail(slug=algorithm_slug)

        with JobInputsCreateStrategy(
            algorithm=algorithm,
            inputs=inputs,
            client=self,
        ) as input_strategy:
            created_inputs = input_strategy()

            return self.algorithm_jobs.create(
                algorithm=algorithm.api_url,
                inputs=created_inputs,
            )

    def update_display_set(
        self,
        *,
        display_set_pk: str,
        values: list[SocketValueSpec],
        title: str | None = None,
        order: int | None | UnsetType = Unset,
    ) -> gcapi.models.DisplaySetPost:
        """
        This function patches an existing display set with the provided values.

        You can use this function, for example, to add metadata to a display set.

        If you provide a value or file for an existing socket of the display
        set, the old value will be overwritten by the new one, hence allowing you
        to update existing display-set values.

        ??? example

            First, retrieve the display sets from your reader study:

            ```Python
            reader_study = client.reader_studies.detail(slug="...")
            items = list(
                client.reader_studies.display_sets.iterate_all(
                    params={"reader_study": reader_study.pk}
                )
            )
            ```

            To then add, for example, a PDF report and a lung volume
            value to the first display set , provide the socket slugs together
            with the respective value or file path as follows:

            ```Python
            from gcapi import SocketValueSpec

            client.update_display_set(
                display_set_pk=items[0].pk,
                values=[
                    SocketValueSpec(socket_slug="report", file="report.pdf"),
                    SocketValueSpec(socket_slug="lung-volume", value=1.9),
                ],
                title="My updated title",
            )
            ```

        Args:
            display_set_pk: The primary key of the display set to update.
            values: A list of socket value specifications.
                Each specification defines a socket slug and exactly one source
                (`value`, `file`, `files`, `existing_image_api_url`, or
                `existing_socket_value`).
            title: An optional new title for the display set. Set to `""` to clear.
            order: An optional new order for the display set. Set to `None` or 0 to auto-assign.

        Returns:
            The updated display item (post) object. Note that not all values will
                be immediately available until the background processing has completed.
        """
        update_kwargs: dict[str, Any] = {"pk": display_set_pk}
        if title is not None:
            update_kwargs["title"] = title
        if order is not Unset:
            update_kwargs["order"] = order or 0

        display_set = self._update_socket_value_set(
            values=values,
            api=self.reader_studies.display_sets,
            **update_kwargs,
        )
        return cast(gcapi.models.DisplaySetPost, display_set)

    def add_case_to_reader_study(
        self,
        *,
        reader_study_slug: str,
        values: list[SocketValueSpec],
        title: str | None = None,
        order: int | None | UnsetType = Unset,
    ) -> gcapi.models.DisplaySetPost:
        """
        This function takes a reader-study slug and a list of socket value specs.
        It then creates a single display set for the reader study.

        Example:
            ```Python
            from gcapi import SocketValueSpec

            client.add_case_to_reader_study(
                reader_study_slug="i-am-a-reader-study",
                values=[
                    SocketValueSpec(socket_slug="report", file="report.pdf"),
                    SocketValueSpec(socket_slug="lung-volume", value=1.9),
                ],
            )
            ```

        ??? tip "Re-using existing images"
            Existing images on Grand Challenge can be re-used by either
            passing an API url, or an existing socket value:

            ```Python
            from gcapi import SocketValueSpec


            image = client.images.detail(pk="ad5...")
            ds = client.reader_studies.display_sets.detail(pk="f5...")
            socket_value = ds.values[0]

            values = [
                SocketValueSpec(socket_slug="slug-0", existing_image_api_url=image.api_url),
                SocketValueSpec(socket_slug="slug-1", existing_socket_value=socket_value),
                SocketValueSpec(socket_slug="slug-2", existing_image_api_url=socket_value.image),
            ]
            ```

        ??? tip "Re-using existing socket values"
            Existing socket values from other display sets can be re-used by
            passing a socket value. The sockets must be the same.

            For instance:

            ```Python
            from gcapi import SocketValueSpec


            ds = client.reader_studies.display_sets.detail(pk="f5...")
            values = [
                SocketValueSpec(socket_slug="slug-0", existing_socket_value=ds.values[0]),
                SocketValueSpec(socket_slug="slug-1", existing_socket_value=ds.values[1]),
            ]
            ```

        Args:
            reader_study_slug: slug for the reader study (e.g. `"i-am-a-reader-study"`).
                You can find this readily in the URL you use to visit the reader-study page:
                `https://grand-challenge.org/reader-studies/i-am-a-reader-study/`

            values: A list of socket value specifications.
                Each specification defines a socket slug and exactly one source
                (`value`, `file`, `files`, `existing_image_api_url`, or
                `existing_socket_value`).

            title: An optional title for the display set.

            order: An optional order for the display set. Set to `None` or 0 to auto-assign.

        Returns:
            The newly created display set (post) object. Note that not all values will
                be immediately available until the background processing has completed.
        """
        creation_kwargs: dict[str, Any] = {"reader_study": reader_study_slug}
        if title is not None:
            creation_kwargs["title"] = title
        if order is not Unset:
            creation_kwargs["order"] = order or 0

        try:
            created_display_set = self._create_socket_value_set(
                values=values,
                api=self.reader_studies.display_sets,
                **creation_kwargs,
            )
        except SocketNotFound as e:
            raise ValueError(
                f"{e.slug} is not an existing socket. "
                f"Please provide one from this list: "
                f"https://grand-challenge.org/components/interfaces/reader-studies/"
            ) from e

        return cast(gcapi.models.DisplaySetPost, created_display_set)

    def update_archive_item(
        self,
        *,
        archive_item_pk: str,
        values: list[SocketValueSpec],
        title: str | None = None,
    ) -> gcapi.models.ArchiveItemPost:
        """
        This function patches an existing archive item with the provided values.

        You can use this function, for example, to add metadata to an archive item.

        If you provide a value or file for an existing socket of the archive
        item, the old value will be overwritten by the new one, hence allowing you
        to update existing archive item values.

        ??? example
            First, retrieve the archive items from your archive:

            ```Python
            archive = client.archives.detail(slug="...")
            items = list(
                client.archive_items.iterate_all(params={"archive": archive.pk})
            )
            ```

            To then add, for example, a PDF report and a lung volume
            value to the first archive item , provide the socket slugs together
            with the respective value or file path as follows:

            ```Python
            from gcapi import SocketValueSpec

            client.update_archive_item(
                archive_item_pk=items[0].pk,
                values=[
                    SocketValueSpec(socket_slug="report", file="report.pdf"),
                    SocketValueSpec(socket_slug="lung-volume", value=1.9),
                ],
                title="Archive item with updated values",
            )
            ```

        Args:
            archive_item_pk: The primary key of the archive item to update.
            values: A list of socket value specifications.
                Each specification defines a socket slug and exactly one source
                (`value`, `file`, `files`, `existing_image_api_url`, or
                `existing_socket_value`).
            title: An optional new title for the archive item. Set to `""` to clear.

        Returns:
            The updated archive item (post) object. Note that not all values will
                be immediately available until the background processing has completed.
        """
        update_kwargs = {"pk": archive_item_pk}
        if title is not None:
            update_kwargs["title"] = title

        archive_item = self._update_socket_value_set(
            values=values,
            api=self.archive_items,
            **update_kwargs,
        )
        return cast(gcapi.models.ArchiveItemPost, archive_item)

    def _fetch_archive_api_url(self, slug: str) -> str:
        if slug not in self._archive_cache:
            self._archive_cache[slug] = self.archives.detail(slug=slug)
        return self._archive_cache[slug].api_url

    def add_case_to_archive(
        self,
        *,
        archive_slug: str,
        values: list[SocketValueSpec],
        title: str | None = None,
    ) -> gcapi.models.ArchiveItemPost:
        """
        This function takes an archive slug and a list of socket value specs.
        It then creates a single archive item for the archive.

        Example:
            ```Python
            from gcapi import SocketValueSpec

            client.add_case_to_archive(
                archive_slug="i-am-an-archive",
                values=[
                    SocketValueSpec(socket_slug="report", file="report.pdf"),
                    SocketValueSpec(socket_slug="lung-volume", value=1.9),
                ],
            )
            ```

        ??? tip "Re-using existing images"
            Existing images on Grand Challenge can be re-used by either
            passing an API url, or an existing socket value:

            ```Python
            from gcapi import SocketValueSpec

            image = client.images.detail(pk="ad5...")
            ai = client.archive_items.detail(pk="f5...")
            socket_value = ai.values[0]

            values = [
                SocketValueSpec(socket_slug="slug-0", existing_image_api_url=image.api_url),
                SocketValueSpec(socket_slug="slug-1", existing_socket_value=socket_value),
                SocketValueSpec(socket_slug="slug-2", existing_image_api_url=socket_value.image),
            ]
            ```
        ??? tip "Re-using existing socket values"
            Existing socket values from other archive items can be re-used by
            passing a socket value. The sockets must be the same.

            For instance:

            ```Python
            from gcapi import SocketValueSpec

            ai = client.archive_items.detail(pk="f5...")
            values = [
                SocketValueSpec(socket_slug="slug-0", existing_socket_value=ai.values[0]),
                SocketValueSpec(socket_slug="slug-1", existing_socket_value=ai.values[1]),
                SocketValueSpec(socket_slug="slug-2", file="some_local_file"),
            ]
            ```

        Args:
            archive_slug: slug for the archive (e.g. `"i-am-an-archive"`).
                You can find this readily in the URL you use to visit the archive page:
                `https://grand-challenge.org/archives/i-am-an-archive/`

            values: A list of socket value specifications.
                Each specification defines a socket slug and exactly one source
                (`value`, `file`, `files`, `existing_image_api_url`, or
                `existing_socket_value`).

            title: An optional title for the archive item.

        Returns:
            The new archive item (post) object. Note that not all values will
                be immediately available until the background processing has completed.
        """
        archive_api_url = self._fetch_archive_api_url(archive_slug)
        creation_kwargs: dict[str, Any] = {"archive": archive_api_url}
        if title is not None:
            creation_kwargs["title"] = title

        try:
            created_archive_item = self._create_socket_value_set(
                values=values,
                api=self.archive_items,
                **creation_kwargs,
            )
        except SocketNotFound as e:
            raise ValueError(
                f"{e.slug} is not an existing socket. "
                f"Please provide one from this list: "
                f"https://grand-challenge.org/components/interfaces/inputs/"
            ) from e

        return cast(gcapi.models.ArchiveItemPost, created_archive_item)

    # Deprecated methods
    def add_cases_to_reader_study(self, *_, **__) -> Any:
        """
        !!! failure Deprecated
            Use `add_case_to_reader_study` instead. This method will be removed in a future version.
        """
        raise NotImplementedError(
            "add_cases_to_reader_study is no longer supported. Use the singular add_case_to_reader_study instead."
        )

    def add_cases_to_archive(self, *_, **__) -> Any:
        """
        !!! failure Deprecated
            Use `add_case_to_archive` instead. This method will be removed in a future version.
        """
        raise NotImplementedError(
            "add_cases_to_archive is no longer supported. Use the singular add_case_to_archive instead."
        )

    def run_external_job(self, *_, **__) -> Any:
        """
        !!! failure Deprecated
            Use `start_algorithm_job` instead. This method will be removed in a future version.
        """
        raise NotImplementedError(
            "run_external_job is no longer supported. Use start_algorithm_job instead."
        )

    def _fetch_socket_detail(
        self, slug: str
    ) -> gcapi.models.ComponentInterface:
        if slug not in self._socket_cache:
            try:
                self._socket_cache[slug] = self.interfaces.detail(slug=slug)
            except ObjectNotFound as e:
                raise SocketNotFound(slug=slug) from e
        return self._socket_cache[slug]

    def _create_socket_value_set(
        self,
        *,
        values: list[SocketValueSpec],
        api: ModifiableMixin,
        **creation_kwargs: Any,
    ) -> SocketValuePostSet:
        with ExitStack() as stack:
            # Prepare the strategies
            strategies: list[SocketValueCreateStrategy] = []
            for spec in values:
                strategy = select_socket_value_strategy(
                    spec=spec,
                    client=self,
                )
                stack.enter_context(strategy)
                strategies.append(strategy)

            # Create the socket-value set
            socket_value_set = api.create(**creation_kwargs)

            # Update the socket-value set with the prepared values
            updated_socket_value_set = api.partial_update(
                pk=socket_value_set.pk,
                values=[s() for s in strategies],
            )

            return updated_socket_value_set

    def _update_socket_value_set(
        self,
        *,
        values: list[SocketValueSpec],
        api: ModifiableMixin,
        **update_kwargs: Any,
    ) -> SocketValuePostSet:
        with ExitStack() as stack:
            # Prepare the strategies
            strategies: list[SocketValueCreateStrategy] = []
            for spec in values:
                strategy = select_socket_value_strategy(
                    spec=spec,
                    client=self,
                )
                stack.enter_context(strategy)
                strategies.append(strategy)

            # Update the socket-value set with the prepared values
            return api.partial_update(
                values=[s() for s in strategies],
                **update_kwargs,
            )
