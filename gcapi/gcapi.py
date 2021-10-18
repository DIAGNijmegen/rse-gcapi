import logging
import os
import re
import uuid
from json import load
from random import randint
from time import sleep
from typing import Any, Dict, List, Type
from urllib.parse import urljoin, urlparse

import jsonschema
from httpx import Client as SyncClient
from httpx import HTTPStatusError, Timeout

from .exceptions import MultipleObjectsReturned, ObjectNotFound

logger = logging.getLogger(__name__)


def is_uuid(s):
    try:
        uuid.UUID(s)
    except ValueError:
        return False
    else:
        return True


def accept_tuples_as_arrays(org):
    return org.redefine(
        "array",
        lambda checker, instance: isinstance(instance, tuple)
        or org.is_type(instance, "array"),
    )


Draft7ValidatorWithTupleSupport = jsonschema.validators.extend(
    jsonschema.Draft7Validator,
    type_checker=accept_tuples_as_arrays(
        jsonschema.Draft7Validator.TYPE_CHECKER
    ),
)


def import_json_schema(filename):
    """
    Loads a json schema from the module's subdirectory "schemas".

    This is not *really* an import but the naming indicates that an ImportError
    is raised in case the json schema cannot be loaded. This should also only
    be called while the module is loaded, not at a later stage, because import
    errors should be raised straight away.

    Parameters
    ----------
    filename: str
        The jsonschema file to be loaded. The filename is relative to the
        "schemas" directory.

    Returns
    -------
    Draft7Validator
        The jsonschema validation object

    Raises
    ------
    ImportError
        Raised if the json schema cannot be loaded.
    """
    filename = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "schemas", filename
    )

    try:
        with open(filename) as f:
            jsn = load(f)
        return Draft7ValidatorWithTupleSupport(
            jsn, format_checker=jsonschema.draft7_format_checker
        )
    except ValueError as e:
        # I want missing/failing json imports to be an import error because that
        # is what they should indicate: a "broken" library
        raise ImportError(
            "Json schema '{file}' cannot be loaded: {error}".format(
                file=filename, error=e
            )
        ) from e


class APIBase:
    _client = None  # type: Client
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
    _client = None  # type: Client

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


class ImagesAPI(APIBase):
    base_path = "cases/images/"


class UploadSessionFilesAPI(APIBase, ModifiableMixin):
    base_path = "cases/upload-sessions/files/"


class UploadSessionsAPI(APIBase, ModifiableMixin):
    base_path = "cases/upload-sessions/"


class WorkstationSessionsAPI(APIBase):
    base_path = "workstations/sessions/"


class ReaderStudyQuestionsAPI(APIBase):
    base_path = "reader-studies/questions/"


class ReaderStudyMineAnswersAPI(APIBase, ModifiableMixin):
    base_path = "reader-studies/answers/mine/"
    validation_schemas = {"GET": import_json_schema("answer.json")}


class ReaderStudyAnswersAPI(APIBase, ModifiableMixin):
    base_path = "reader-studies/answers/"

    validation_schemas = {
        "GET": import_json_schema("answer.json"),
        "POST": import_json_schema("post-answer.json"),
    }

    sub_apis = {"mine": ReaderStudyMineAnswersAPI}

    mine = None  # type: ReaderStudyMineAnswersAPI

    def _process_request_arguments(self, method, data):
        if is_uuid(data.get("question", "")):
            data["question"] = urljoin(
                urljoin(
                    self._client.base_url, ReaderStudyQuestionsAPI.base_path
                ),
                data["question"] + "/",
            )

        return ModifiableMixin._process_request_arguments(self, method, data)


class ReaderStudiesAPI(APIBase):
    base_path = "reader-studies/"
    validation_schemas = {"GET": import_json_schema("reader-study.json")}

    sub_apis = {
        "answers": ReaderStudyAnswersAPI,
        "questions": ReaderStudyQuestionsAPI,
    }

    answers = None  # type: ReaderStudyAnswersAPI
    questions = None  # type: ReaderStudyQuestionsAPI

    def ground_truth(self, pk, case_pk):
        result = self._client(
            method="GET",
            path=urljoin(self.base_path, pk + "/ground-truth/" + case_pk),
        )
        return result


class AlgorithmsAPI(APIBase):
    base_path = "algorithms/"


class AlgorithmResultsAPI(APIBase):
    base_path = "algorithms/results/"


class AlgorithmJobsAPI(APIBase, ModifiableMixin):
    base_path = "algorithms/jobs/"

    def by_input_image(self, pk):
        return self.iterate_all(params={"image": pk})


class ArchivesAPI(APIBase):
    base_path = "archives/"


class RetinaLandmarkAnnotationSetsAPI(APIBase, ModifiableMixin):
    base_path = "retina/landmark-annotation/"

    validation_schemas = {
        "GET": import_json_schema("landmark-annotation.json"),
        "POST": import_json_schema("post-landmark-annotation.json"),
    }

    def for_image(self, pk):
        result = self._client(
            method="GET", path=self.base_path, params={"image_id": pk}
        )
        for i in result:
            self._verify_against_schema(i)
        return result


class RetinaPolygonAnnotationSetsAPI(APIBase, ModifiableMixin):
    base_path = "retina/polygon-annotation-set/"
    validation_schemas = {
        "GET": import_json_schema("polygon-annotation.json"),
        "POST": import_json_schema("post-polygon-annotation.json"),
    }


class RetinaSinglePolygonAnnotationsAPI(APIBase, ModifiableMixin):
    base_path = "retina/single-polygon-annotation/"
    validation_schemas = {
        "GET": import_json_schema("single-polygon-annotation.json"),
        "POST": import_json_schema("post-single-polygon-annotation.json"),
    }


class RetinaETDRSGridAnnotationsAPI(APIBase, ModifiableMixin):
    base_path = "retina/etdrs-grid-annotation/"
    validation_schemas = {
        "GET": import_json_schema("etdrs-annotation.json"),
        "POST": import_json_schema("post-etdrs-annotation.json"),
    }


class UploadsAPI(APIBase):
    base_path = "uploads/"
    chunk_size = 32 * 1024 * 1024
    n_presigned_urls = 5  # number of pre-signed urls to generate
    max_retries = 10

    def create(self, *, filename):
        return self._client(
            method="POST",
            path=self.base_path,
            json={"filename": str(filename)},
        )

    def generate_presigned_urls(self, *, pk, s3_upload_id, part_numbers):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/generate-presigned-urls/"
        )
        return self._client(
            method="PATCH", path=url, json={"part_numbers": part_numbers}
        )

    def abort_multipart_upload(self, *, pk, s3_upload_id):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/abort-multipart-upload/"
        )
        return self._client(method="PATCH", path=url)

    def complete_multipart_upload(self, *, pk, s3_upload_id, parts):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/complete-multipart-upload/"
        )
        return self._client(method="PATCH", path=url, json={"parts": parts})

    def list_parts(self, *, pk, s3_upload_id):
        url = urljoin(self.base_path, f"{pk}/{s3_upload_id}/list-parts/")
        return self._client(path=url)

    def upload_fileobj(self, *, fileobj, filename):
        user_upload = self.create(filename=filename)

        pk = user_upload["pk"]
        s3_upload_id = user_upload["s3_upload_id"]

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
        e = Exception

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
                    sleep((2 ** num_retries) + (randint(0, 1000) / 1000))
                else:
                    raise
        else:
            raise e

        return result


class WorkstationConfigsAPI(APIBase):
    base_path = "workstations/configs/"


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


class Client(SyncClient):
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

        self.images = ImagesAPI(client=self)
        self.reader_studies = ReaderStudiesAPI(client=self)
        self.sessions = WorkstationSessionsAPI(client=self)
        self.uploads = UploadsAPI(client=self)
        self.algorithms = AlgorithmsAPI(client=self)
        self.algorithm_results = AlgorithmResultsAPI(client=self)
        self.algorithm_jobs = AlgorithmJobsAPI(client=self)
        self.archives = ArchivesAPI(client=self)
        self.workstation_configs = WorkstationConfigsAPI(client=self)
        self.retina_landmark_annotations = RetinaLandmarkAnnotationSetsAPI(
            client=self
        )
        self.retina_polygon_annotation_sets = RetinaPolygonAnnotationSetsAPI(
            client=self
        )
        self.retina_single_polygon_annotations = RetinaSinglePolygonAnnotationsAPI(
            client=self
        )
        self.retina_etdrs_grid_annotations = RetinaETDRSGridAnnotationsAPI(
            client=self
        )
        self.raw_image_upload_session_files = UploadSessionFilesAPI(
            client=self
        )
        self.raw_image_upload_sessions = UploadSessionsAPI(client=self)

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
