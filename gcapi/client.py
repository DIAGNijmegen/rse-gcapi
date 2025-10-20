import logging
import os
import re
import uuid
import warnings
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from random import randint
from time import sleep
from typing import IO, Any, Callable, Optional, Union
from urllib.parse import urljoin

import httpx
from httpx import URL, HTTPStatusError, Timeout

import gcapi.models
from gcapi.apibase import APIBase, ModifiableMixin
from gcapi.check_version import check_version
from gcapi.create_strategies import (
    JobInputsCreateStrategy,
    SocketValueCreateStrategy,
    select_socket_value_strategy,
)
from gcapi.exceptions import ObjectNotFound, SocketNotFound
from gcapi.retries import BaseRetryStrategy, SelectiveBackoffStrategy
from gcapi.transports import RetryTransport
from gcapi.typing import SocketValueSet, SocketValueSetDescription

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
        filename: Union[str, Path],
        image_type: Optional[str] = None,
        pk: Optional[str] = None,
        url: Optional[str] = None,
        files: Optional[list] = None,
        **params: Any,
    ) -> list[Path]:
        """
        Download image files to local filesystem.

        Args:
            filename: Base filename for downloaded files. Extension is added automatically.
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

            files = image.files

        # Make sure file destination exists
        p = Path(filename).absolute()
        directory = p.parent
        directory.mkdir(parents=True, exist_ok=True)
        basename = p.name

        # Download the files
        downloaded_files = []
        for file in files:
            if image_type and file.image_type != image_type:
                continue

            data = self._client(
                method="GET", url=file.file, follow_redirects=True
            ).content

            suffix = file.file.split(".")[-1]
            local_file = directory / f"{basename}.{suffix}"
            with local_file.open("wb") as fp:
                fp.write(data)

            downloaded_files.append(local_file)

        return downloaded_files


class UploadSessionsAPI(
    ModifiableMixin[gcapi.models.RawImageUploadSession],
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

    def create(self, *, filename: Union[str, Path]) -> gcapi.models.UserUpload:
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
    ) -> dict[str, str]:
        """
        Generate presigned URLs for multipart upload parts.

        Args:
            pk: Primary key of the upload session.
            s3_upload_id: S3 multipart upload identifier.
            part_numbers: List of part numbers to generate URLs for.

        Returns:
            Dictionary containing presigned URLs for each part number.
        """
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/generate-presigned-urls/"
        )
        return self._client(
            method="PATCH", path=url, json={"part_numbers": part_numbers}
        )

    def abort_multipart_upload(self, *, pk: str, s3_upload_id: str) -> dict:
        """
        Abort a multipart upload session.

        Args:
            pk: Primary key of the upload session.
            s3_upload_id: S3 multipart upload identifier to abort.

        Returns:
            Response from the API.
        """
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/abort-multipart-upload/"
        )
        return self._client(method="PATCH", path=url)

    def complete_multipart_upload(
        self, *, pk: str, s3_upload_id: str, parts: list
    ) -> dict:
        """
        Complete a multipart upload session.

        Args:
            pk: Primary key of the upload session.
            s3_upload_id: S3 multipart upload identifier.
            parts: List of completed parts with ETag and PartNumber.

        Returns:
            Response from the API containing upload completion details.
        """
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/complete-multipart-upload/"
        )
        return self._client(method="PATCH", path=url, json={"parts": parts})

    def list_parts(self, *, pk: str, s3_upload_id: str) -> dict:
        """
        List parts of a multipart upload.

        Args:
            pk: Primary key of the upload session.
            s3_upload_id: S3 multipart upload identifier.

        Returns:
            Response containing list of uploaded parts.
        """
        url = urljoin(self.base_path, f"{pk}/{s3_upload_id}/list-parts/")
        return self._client(path=url)

    def upload_fileobj(
        self,
        *,
        fileobj: IO,
        filename: str,
    ) -> gcapi.models.UserUpload:
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

        result = self.complete_multipart_upload(
            pk=pk, s3_upload_id=s3_upload_id, parts=parts
        )
        return self.model(**result)  # noqa: B901

    def _put_fileobj(self, *, fileobj, pk, s3_upload_id):
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

    def _get_next_presigned_urls(self, *, pk, s3_upload_id, part_number):
        response = self.generate_presigned_urls(
            pk=pk,
            s3_upload_id=s3_upload_id,
            part_numbers=[
                *range(part_number, part_number + self.n_presigned_urls)
            ],
        )
        return response["presigned_urls"]

    def _put_chunk(self, *, chunk, url):
        num_retries = 0
        e = Exception()

        if isinstance(chunk, BytesIO):
            chunk = chunk.read()

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
        retry_strategy: Optional[Callable[[], BaseRetryStrategy]] = None,
    ):
        """
        Args:
            token (str, optional): Authorization token for API access. If not provided, will be read
                from GRAND_CHALLENGE_AUTHORIZATION environment variable.
            base_url (str, optional): Base URL for the API, by default "https://grand-challenge.org/api/v1/".
            verify (bool, optional): Whether to verify SSL certificates, by default True.
            timeout (float, optional): Request timeout in seconds, by default 60.0.
            retry_strategy (callable, optional): Factory function that returns a retry strategy instance. If None,
                uses SelectiveBackoffStrategy with default parameters.
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

        self._api_meta = ApiDefinitions()
        for name, cls in self._api_meta.__annotations__.items():
            setattr(self._api_meta, name, cls(client=self))

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

    def _upload_image_files(self, *, files, **kwargs):
        uploads = []
        for file in files:
            with open(file, "rb") as f:
                uploads.append(
                    self.uploads.upload_fileobj(
                        fileobj=f, filename=os.path.basename(file)
                    )
                )

        return self.raw_image_upload_sessions.create(
            uploads=[u.api_url for u in uploads], **kwargs
        )

    def _upload_file(self, value):
        with open(value[0], "rb") as f:
            upload = self.uploads.upload_fileobj(
                fileobj=f, filename=value[0].name
            )
        return upload

    def upload_cases(  # noqa: C901
        self,
        *,
        files: list[Union[str, Path]],
        archive: Optional[str] = None,
        answer: Optional[str] = None,
        archive_item: Optional[str] = None,
        display_set: Optional[str] = None,
        interface: Optional[str] = None,
    ) -> gcapi.models.RawImageUploadSession:
        """
        Uploads a set of files to an archive, archive item or display set.
        A new upload session will be created on grand challenge to import and
        standardise your file(s). This function will return this new upload
        session object, that you can query for the import status. If this
        import is successful, the new image(s) will then be added to the selected
        archive, archive item or reader study.
        You will need to provide the slugs of the archive or reader study or the
        pk of the archive item to pass the images along to.
        You can find the slug in the url of the object that you want
        to use. For instance, if you want to use the archive at
            https://grand-challenge.org/archives/corads-ai/
        the slug for this is "corads-ai", so you would call this function with
            upload_cases(files=[...], archive="corads-ai")
        For archive uploads, you can additionally specify the interface slug
        for the to be created archive items. For archive item uploads, the
        interface is mandatory. If you define an already existing interface,
        the old file associated with that interface will be replaced by the new file.
        You can find a list of interfaces here:
        https://grand-challenge.org/algorithms/interfaces/
        The interface slug corresponds to the lowercase hyphenated title of the
        interface, e.g. generic-medical-image for Generic Medical Image.

        Args:
            files (list[Union[str, Path]]): The list of files on disk that form 1 Image. These can be a set of
                .mha, .mhd, .raw, .zraw, .dcm, .nii, .nii.gz, .tiff, .png, .jpeg,
                .jpg, .svs, .vms, .vmu, .ndpi, .scn, .mrxs and/or .bif files.
            archive (Optional[str]): The slug of the archive to use.
            answer (Optional[str]): The pk of the reader study answer to use.
            archive_item (Optional[str]): The pk of the archive item to use.
            display_set (Optional[str]): The pk of the display set to use.
            interface (Optional[str]): The slug of the interface to use. Can only be defined for archive
                and archive item uploads.

        Returns:
            The created upload session.

        Raises:
            ValueError: If the input parameters are not valid.
        """

        warnings.warn(
            message=(
                "Using upload_cases is deprecated "
                "and will be removed in the next release. "
                "Suggestion: use the specific functions: "
                "update_archive_item, update_display_set, or add_cases_to_archive"
            ),
            category=DeprecationWarning,
            stacklevel=3,
        )

        upload_session_data = {}

        if len(files) == 0:
            raise ValueError("You must specify the files to upload")

        if archive is not None:
            upload_session_data["archive"] = archive

        if answer is not None:
            upload_session_data["answer"] = answer

        if archive_item is not None:
            upload_session_data["archive_item"] = archive_item

        if display_set is not None:
            upload_session_data["display_set"] = display_set

        if len(upload_session_data) != 1:
            raise ValueError(
                "One of archive, archive_item, display_set, answer or "
                "reader_study can be set"
            )

        if interface:
            upload_session_data["interface"] = interface

        if interface and not (archive or archive_item or display_set):
            raise ValueError(
                "An interface can only be defined for archive, archive item "
                "or display set uploads."
            )

        if archive_item and not interface:
            raise ValueError(
                "You need to define an interface for archive item uploads."
            )

        if display_set and not interface:
            raise ValueError(
                "You need to define an interface for display set uploads."
            )

        raw_image_upload_session = self._upload_image_files(
            files=files, **upload_session_data
        )

        return raw_image_upload_session

    def run_external_job(
        self,
        *,
        algorithm: Union[str, gcapi.models.Algorithm],
        inputs: SocketValueSetDescription,
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
            passing an API url, or a socket value:

            ```Python
            image = client.images.detail(pk="ad5...")
            # Alternatively, you can also use:
            ai = client.archive_items.detail(pk="f5...")
            socket_value = ai.values[0]

            archive_items = [
                {
                    "slug_0": image.api_url,
                    "slug_1": socket_value,
                    "slug_2": socket_value.image.api_url,
                }
            ]
            ```

            One can also provide a same-socket socket value:

            ```Python
            ai = client.archive_items.detail(pk="f5...")
            archive_items = [
                {
                    "slug_0": ai.values[0],
                    "slug_1": ai.values[1],
                    "slug_2": "some_local_file",
                },
            ]
            ```


        Args:
            algorithm: You can find this in the
                url of the algorithm that you want to use. For instance,
                if you want to use the algorithm at: `https://grand-challenge.org/algorithms/corads-ai/`
                the slug for this algorithm is `"corads-ai"`.

                inputs (SocketValueSetDescription): For each input socket defined on the algorithm you need to provide a
                key-value pair, the key being the slug of the socket, the value being
                the value for the socket::

                ```Python
                {
                    "slug_0": ["filepath_0", ...],
                    "slug_1": "filepath_0",
                    "slug_2": pathlib.Path("filepath_0"),
                    ...
                    "slug_n": {"json": "value"},
                }
                ```

                Where the file paths are local paths to the files making up a
                single image. For file-kind sockets the file path can only
                reference a single file. For json-kind sockets any value that
                is valid for the sockets can directly be passed, or a filepath
                to a file that contain the value can be provided.

        Returns:
            The created job
        """

        if isinstance(algorithm, str):
            algorithm = self.algorithms.detail(slug=algorithm)

        input_strategy = JobInputsCreateStrategy(
            algorithm=algorithm,
            inputs=inputs,
            client=self,
        )

        inputs = input_strategy()

        return self.algorithm_jobs.create(
            algorithm=algorithm.api_url,
            inputs=inputs,
        )

    def update_display_set(
        self, *, display_set_pk: str, values: SocketValueSetDescription
    ) -> gcapi.models.DisplaySetPost:
        """
        This function updates an existing display set with the provided values
        and returns the updated display set.

        You can use this function, for example, to add metadata to a display set.

        If you provide a value or file for an existing interface of the display
        set, the old value will be overwritten by the new one, hence allowing you
        to update existing display-set values.

        ??? example

            First, retrieve the display_set from your archive:

            ```Python
            reader_study = client.reader_studies.detail(slug="...")
            items = list(
                client.reader_studies.display_sets.iterate_all(
                    params={"reader_study": reader_study.pk}
                )
            )
            ```

            To then add, for example, a PDF report and a lung volume
            value to the first display set , provide the interface slugs together
            with the respective value or file path as follows:

            ```Python
            client.update_display_set(
                display_set_pk=items[0].id,
                values={
                    "report": [...],
                    "lung-volume": 1.9,
                },
            )
            ```

        Args:
            display_set_pk (str): The primary key of the display set to update.

            values (SocketValueSetDescription): The values to update the display set with.

        Returns:
            The updated display set
        """
        ds = self.reader_studies.display_sets.detail(pk=display_set_pk)
        return self._update_socket_value_set(
            target=ds,
            description=values,
            api=self.reader_studies.display_sets,
        )

    def add_cases_to_reader_study(
        self,
        *,
        reader_study: Union[str, gcapi.models.ReaderStudy],
        display_sets: list[SocketValueSetDescription],
    ) -> list[str]:
        """
        This function takes an reader-study slug or model and a list of display-set
        descriptions. It then creates the display-sets for the reader study.

        ??? tip "Re-using existing images"
            Existing images on Grand Challenge can be re-used by either
            passing an API url, or a socket value (display set):

            ```Python
                image = client.images.detail(pk="ad5...")
                ds = client.reader_studies.display_sets.detail(pk="f5...")
                socket_value = ds.values[0]

                display_sets = [
                    {
                        "slug_0": image.api_url,
                        "slug_1": socket_value,
                        "slug_2": socket_value.image,
                    }
                ]
            ```

            One can also provide a same-socket socket value:

            ```Python
            ds = client.reader_studies.display_sets.detail(pk="f5...")
            display_sets = [
                {
                    "slug_0": ds.values[0],
                    "slug_1": ds.values[1],
                    "slug_2": "some_local_file",
                },
            ]
            ```

        Args:
            reader_study (Union[str, gcapi.models.ReaderStudy]): slug for the reader
                study (e.g. `"i-am-a-reader-study"`). You can find this readily in the
                URL you use to visit the reader-study page:
                `https://grand-challenge.org/reader-studies/i-am-a-reader-study/`

            display_sets (list[SocketValueSetDescription]): The format for the
                descriptions of display sets are as follows:

                ```Python
                [
                    {
                        "slug_0": ["filepath_0", ...],
                        "slug_1": "filepath_0",
                        "slug_2": pathlib.Path("filepath_0"),
                        ...
                        "slug_n": {"json": "value"}

                    },
                    ...
                ]
                ```

                Where the file paths are local paths to the files making up a
                single image. For file-kind sockets the file path can only
                reference a single file. For json-kind sockets any value that
                is valid for the sockets can directly be passed, or a filepath
                to a file that contain the value can be provided.

        Returns:
            The pks of the newly created display sets.
        """

        if isinstance(reader_study, gcapi.models.ReaderStudy):
            reader_study = reader_study.slug
        try:
            created_display_sets = self._create_socket_value_sets(
                creation_kwargs={"reader_study": reader_study},
                descriptions=display_sets,
                api=self.reader_studies.display_sets,
            )
        except SocketNotFound as e:
            raise ValueError(
                f"{e.slug} is not an existing interface. "
                f"Please provide one from this list: "
                f"https://grand-challenge.org/components/interfaces/reader-studies/"
            ) from e

        return [ds.pk for ds in created_display_sets]

    def update_archive_item(
        self,
        *,
        archive_item_pk: str,
        values: SocketValueSetDescription,
    ) -> gcapi.models.ArchiveItemPost:
        """
        This function updates an existing archive item with the provided values
        and returns the updated archive item.

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
            client.update_archive_item(
                archive_item_pk=items[0].id,
                values={
                    "report": [...],
                    "lung-volume": 1.9,
                },
            )
            ```



        Args:
            archive_item_pk (str): The primary key of the archive item to update.
            values (SocketValueSetDescription): The values to update the archive
                item with.

        Returns:
            The updated archive item
        """
        item = self.archive_items.detail(pk=archive_item_pk)
        return self._update_socket_value_set(
            target=item,
            description=values,
            api=self.archive_items,
        )

    def add_cases_to_archive(
        self,
        *,
        archive: Union[str, gcapi.models.Archive],
        archive_items: list[SocketValueSetDescription],
    ) -> list[str]:
        """
        This function takes an archive slug or model and a list of archive item
        descriptions and creates the archive item to be used on the platform.

        ??? tip "Re-using existing images"
            Existing images on Grand Challenge can be re-used by either
            passing an API url, or a socket value (archive item):

            ```Python
            image = client.images.detail(pk="ad5...")
            ai = client.archive_items.detail(pk="f5...")
            socket_value = ai.values[0]

            archive_items = [
                {
                    "slug_0": image.api_url,
                    "slug_1": socket_value,
                    "slug_2": socket_value.image,
                }
            ]
            ```

            One can also provide a same-socket socket value:

            ```Python
            ai = client.archive_items.detail(pk="f5...")
            archive_items = [
                {
                    "slug_0": ai.values[0],
                    "slug_1": ai.values[1],
                    "slug_2": "some_local_file",
                },
            ]
            ```

        Args:
            archive (Union[str, gcapi.models.Archive]): slug for the archive (e.g. `"i-am-an-archive"`).
                You can find this readily in the URL you use to visit the archive page:
                `https://grand-challenge.org/archives/i-am-an-archive/`

            archive_items (list[SocketValueSetDescription]): The format for the descriptions of
                archive items are as follows:

                ```Python
                [
                    {
                        "slug_0": ["filepath_0", ...],
                        "slug_1": "filepath_0",
                        "slug_2": pathlib.Path("filepath_0"),
                        ...
                        "slug_n": {"json": "value"}

                    },
                    ...
                ]
                ```

                Where the file paths are local paths to the files making up a
                single image. For file-kind sockets the file path can only
                reference a single file. For json-kind sockets any value that
                is valid for the sockets can directly be passed, or a filepath
                to a file that contain the value can be provided.

        Returns:
            The pks of the newly created archive items.
        """

        if isinstance(archive, str):
            archive = self.archives.detail(slug=archive)

        try:
            created_archive_items = self._create_socket_value_sets(
                creation_kwargs={"archive": archive.api_url},
                descriptions=archive_items,
                api=self.archive_items,
            )
        except SocketNotFound as e:
            raise ValueError(
                f"{e.slug} is not an existing interface. "
                f"Please provide one from this list: "
                f"https://grand-challenge.org/components/interfaces/inputs/"
            ) from e

        return [ai.pk for ai in created_archive_items]

    def _fetch_socket_detail(
        self,
        slug_or_socket,
        cache=None,
    ) -> gcapi.models.ComponentInterface:
        if isinstance(slug_or_socket, gcapi.models.ComponentInterface):
            return slug_or_socket
        else:
            slug = slug_or_socket

        if cache and slug in cache:
            return cache[slug]
        try:
            interface = self.interfaces.detail(slug=slug)
        except ObjectNotFound as e:
            raise SocketNotFound(slug=slug) from e
        else:
            if cache:
                cache[slug] = interface

            return interface

    def _create_socket_value_sets(
        self,
        *,
        creation_kwargs: dict,
        descriptions: list[SocketValueSetDescription],
        api: ModifiableMixin,
    ):
        interface_cache: dict[str, gcapi.models.ComponentInterface] = {}

        # Firstly, prepare ALL the strategies
        strategies_per_value_set: list[list[SocketValueCreateStrategy]] = []
        for description in descriptions:
            strategy_per_value = []

            for socket_slug, source in description.items():
                socket = self._fetch_socket_detail(
                    slug_or_socket=socket_slug,
                    cache=interface_cache,
                )
                strategy = select_socket_value_strategy(
                    client=self,
                    socket=socket,
                    source=source,
                )
                strategy_per_value.append(strategy)

            strategies_per_value_set.append(strategy_per_value)

        # Secondly, create + update socket-value sets
        socket_value_sets: list[SocketValueSet] = []
        for strategies in strategies_per_value_set:
            socket_value_set = api.create(**creation_kwargs)
            values = [s() for s in strategies]
            update_socket_value_set = api.partial_update(
                pk=socket_value_set.pk, values=values
            )
            socket_value_sets.append(update_socket_value_set)

        return socket_value_sets

    def _update_socket_value_set(
        self,
        *,
        target: SocketValueSet,
        description: SocketValueSetDescription,
        api: ModifiableMixin,
    ):
        strategies = []

        for socket_slug, source in description.items():
            socket: gcapi.models.ComponentInterface = (
                self._fetch_socket_detail(socket_slug)
            )

            strategy = select_socket_value_strategy(
                source=source,
                socket=socket,
                client=self,
            )
            strategies.append(strategy)

        values = [s() for s in strategies]

        return api.partial_update(pk=target.pk, values=values)
