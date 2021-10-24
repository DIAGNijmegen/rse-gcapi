import logging
import re
from typing import Any, Dict, List, TYPE_CHECKING, Generator
from urllib.parse import urljoin, urlparse
import os
import uuid
from io import BytesIO
from json import load
from random import randint
from time import sleep

import httpx
from httpx import Timeout, URL
import jsonschema
from httpx import HTTPStatusError

from gcapi.apibase import APIBase, ModifiableMixin, ClientInterface
from gcapi.sync_async_hybrid_support import CapturedCall

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
            data["question"] = str(
                self._client.base_url.join(
                    ReaderStudyQuestionsAPI.base_path
                ).join(data["question"] + "/")
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
        return (
            yield self.yield_request(
                method="GET",
                path=self.base_path.join(pk + "/ground-truth/" + case_pk,),
            )
        )


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
        result = yield self.yield_request(
            method="GET", path=self.base_path, params={"image_id": pk}
        )
        for i in result:
            self.verify_against_schema(i)
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
        return (
            yield self.yield_request(
                method="POST",
                path=self.base_path,
                json={"filename": str(filename)},
            )
        )

    def generate_presigned_urls(self, *, pk, s3_upload_id, part_numbers):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/generate-presigned-urls/"
        )
        return (
            yield self.yield_request(
                method="PATCH", path=url, json={"part_numbers": part_numbers}
            )
        )

    def abort_multipart_upload(self, *, pk, s3_upload_id):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/abort-multipart-upload/"
        )
        return (yield self.yield_request(method="PATCH", path=url))

    def complete_multipart_upload(self, *, pk, s3_upload_id, parts):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/complete-multipart-upload/"
        )
        return (
            yield self.yield_request(
                method="PATCH", path=url, json={"parts": parts}
            )
        )

    def list_parts(self, *, pk, s3_upload_id):
        url = urljoin(self.base_path, f"{pk}/{s3_upload_id}/list-parts/")
        return (yield self.yield_request(path=url))

    def upload_fileobj(self, *, fileobj, filename):
        user_upload = yield from self.create(filename=filename)

        pk = user_upload["pk"]
        s3_upload_id = user_upload["s3_upload_id"]

        try:
            parts = yield from self._put_fileobj(
                fileobj=fileobj, pk=pk, s3_upload_id=s3_upload_id
            )
        except Exception:
            yield from self.abort_multipart_upload(
                pk=pk, s3_upload_id=s3_upload_id
            )
            raise

        return (
            yield from self.complete_multipart_upload(
                pk=pk, s3_upload_id=s3_upload_id, parts=parts
            )
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
                    (
                        yield from self._get_next_presigned_urls(
                            pk=pk,
                            s3_upload_id=s3_upload_id,
                            part_number=part_number,
                        )
                    )
                )

            response = yield from self._put_chunk(
                chunk=chunk, url=presigned_urls[str(part_number)]
            )

            parts.append(
                {"ETag": response.headers["ETag"], "PartNumber": part_number}
            )

            part_number += 1

        return parts

    def _get_next_presigned_urls(self, *, pk, s3_upload_id, part_number):
        response = yield from self.generate_presigned_urls(
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

        if isinstance(chunk, BytesIO):
            chunk = chunk.read()

        while num_retries < self.max_retries:
            try:
                result = yield self.yield_request.request(
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


class ApiDefinitions:
    images: ImagesAPI
    reader_studies: ReaderStudiesAPI
    sessions: WorkstationSessionsAPI
    uploads: UploadsAPI
    algorithms: AlgorithmsAPI
    algorithm_results: AlgorithmResultsAPI
    algorithm_jobs: AlgorithmJobsAPI
    archives: ArchivesAPI
    workstation_configs: WorkstationConfigsAPI
    retina_landmark_annotations: RetinaLandmarkAnnotationSetsAPI
    retina_polygon_annotation_sets: RetinaPolygonAnnotationSetsAPI
    retina_single_polygon_annotations: RetinaSinglePolygonAnnotationsAPI
    retina_etdrs_grid_annotations: RetinaETDRSGridAnnotationsAPI
    raw_image_upload_session_files: UploadSessionFilesAPI
    raw_image_upload_sessions: UploadSessionsAPI


class ClientBase(ApiDefinitions, ClientInterface):
    # Make MyPy happy, this is a mixin now, so the dependent values will
    # come in through a side-channel
    if TYPE_CHECKING:
        _Base = httpx.Client

    _api_meta: ApiDefinitions

    def __init__(
        self,
        init_base_cls,
        token: str = "",
        base_url: str = "https://grand-challenge.org/api/v1/",
        verify: bool = True,
        timeout: float = 60.0,
    ):
        init_base_cls.__init__(
            self, verify=verify, timeout=Timeout(timeout=timeout)
        )

        self.headers.update({"Accept": "application/json"})
        self._auth_header = _generate_auth_header(token=token)

        self.base_url = base_url
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
            raise AttributeError(
                f"'ClientBase' has no function or API '{item}'"
            )

    def validate_url(self, url):
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
    ) -> Generator[CapturedCall, Any, Any]:
        if not url:
            url = self.base_url.join(path)
        if extra_headers is None:
            extra_headers = {}
        if json is not None:
            extra_headers["Content-Type"] = "application/json"

        self.validate_url(url)

        response = yield CapturedCall(
            func=self.request,
            args=(),
            kwargs={
                "method": method,
                "url": str(url),
                "files": {} if files is None else files,
                "data": {} if data is None else data,
                "headers": {
                    **self.headers,
                    **self._auth_header,
                    **extra_headers,
                },
                "params": {} if params is None else params,
                "json": json,
            },
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
