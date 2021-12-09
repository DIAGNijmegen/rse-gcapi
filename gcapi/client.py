import logging
import os
import re
import uuid
from io import BytesIO
from json import load
from pathlib import Path
from random import randint
from time import sleep
from typing import Any, Dict, Generator, List, TYPE_CHECKING, Union
from urllib.parse import urljoin

import httpx
import jsonschema
from httpx import HTTPStatusError
from httpx import Timeout, URL

from gcapi.apibase import APIBase, ClientInterface, ModifiableMixin
from gcapi.sync_async_hybrid_support import CapturedCall, mark_generator

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
    except (OSError, ValueError) as e:
        # I want missing/failing json imports to be an import error because that
        # is what they should indicate: a "broken" library
        raise ImportError(
            "Json schema '{file}' cannot be loaded: {error}".format(
                file=filename, error=e
            )
        ) from e


class ImagesAPI(APIBase):
    base_path = "cases/images/"

    def download(
        self,
        *,
        filename: Union[str, Path],  # extension is added automatically
        image_type: str = None,  # restrict download to a particular image type
        pk=None,
        url=None,
        files=None,
        **params,
    ):
        if len([p for p in (pk, url, files, params) if p]) != 1:
            raise ValueError(
                "Exactly one of pk, url, files or params must be specified"
            )

        # Retrieve details of the image if needed
        if files is None:
            if pk is not None:
                image = yield from self.detail(pk=pk)
            elif url is not None:
                image = yield self.yield_request(method="GET", url=url)
                self.verify_against_schema(image)
            else:
                image = yield from self.detail(**params)

            files = image["files"]

        # Make sure file destination exists
        p = Path(filename).absolute()
        directory = p.parent
        directory.mkdir(parents=True, exist_ok=True)
        basename = p.name

        # Download the files
        downloaded_files = []
        for file in files:
            if image_type and file["image_type"] != image_type:
                continue

            data = (
                yield self.yield_request(
                    method="GET", url=file["file"], follow_redirects=True
                )
            ).content

            suffix = file["file"].split(".")[-1]
            local_file = directory / f"{basename}.{suffix}"
            with local_file.open("wb") as fp:
                fp.write(data)

            downloaded_files.append(local_file)

        return downloaded_files


class UploadSessionsAPI(ModifiableMixin, APIBase):
    base_path = "cases/upload-sessions/"


class WorkstationSessionsAPI(APIBase):
    base_path = "workstations/sessions/"


class ReaderStudyQuestionsAPI(APIBase):
    base_path = "reader-studies/questions/"


class ReaderStudyMineAnswersAPI(ModifiableMixin, APIBase):
    base_path = "reader-studies/answers/mine/"
    validation_schemas = {"GET": import_json_schema("answer.json")}


class ReaderStudyAnswersAPI(ModifiableMixin, APIBase):
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
                path=urljoin(
                    self.base_path, pk + "/ground-truth/" + case_pk + "/"
                ),
            )
        )


class AlgorithmsAPI(APIBase):
    base_path = "algorithms/"


class AlgorithmResultsAPI(APIBase):
    base_path = "algorithms/results/"


class AlgorithmJobsAPI(ModifiableMixin, APIBase):
    base_path = "algorithms/jobs/"

    @mark_generator
    def by_input_image(self, pk):
        yield from self.iterate_all(params={"image": pk})


class ArchivesAPI(APIBase):
    base_path = "archives/"


class RetinaLandmarkAnnotationSetsAPI(ModifiableMixin, APIBase):
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


class RetinaPolygonAnnotationSetsAPI(ModifiableMixin, APIBase):
    base_path = "retina/polygon-annotation-set/"
    validation_schemas = {
        "GET": import_json_schema("polygon-annotation.json"),
        "POST": import_json_schema("post-polygon-annotation.json"),
    }


class RetinaSinglePolygonAnnotationsAPI(ModifiableMixin, APIBase):
    base_path = "retina/single-polygon-annotation/"
    validation_schemas = {
        "GET": import_json_schema("single-polygon-annotation.json"),
        "POST": import_json_schema("post-single-polygon-annotation.json"),
    }


class RetinaETDRSGridAnnotationsAPI(ModifiableMixin, APIBase):
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

        return (  # noqa: B901
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
    raw_image_upload_sessions: UploadSessionsAPI


class ClientBase(ApiDefinitions, ClientInterface):
    # Make MyPy happy, this is a mixin now, so the dependent values will
    # come in through a side-channel
    if TYPE_CHECKING:
        _Base = httpx.Client

    _api_meta: ApiDefinitions
    __org_api_meta: ApiDefinitions

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

        self.base_url = URL(base_url)
        if self.base_url.scheme.lower() != "https":
            raise RuntimeError("Base URL must be https")

        self._api_meta = ApiDefinitions()
        self.__org_api_meta = ApiDefinitions()
        for name, cls in self._api_meta.__annotations__.items():
            setattr(self._api_meta, name, cls(client=self))
            setattr(self.__org_api_meta, name, cls(client=self))

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
        follow_redirects=False,
    ) -> Generator[CapturedCall, Any, Any]:
        if url:
            url = URL(url)
        else:
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
                "follow_redirects": follow_redirects,
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

    def _upload_files(self, *, files, **kwargs):
        uploads = []
        for file in files:
            with open(file, "rb") as f:
                uploads.append(
                    (
                        yield from self.__org_api_meta.uploads.upload_fileobj(
                            fileobj=f, filename=file.name
                        )
                    )
                )

        return (
            yield from self.__org_api_meta.raw_image_upload_sessions.create(
                uploads=[u["api_url"] for u in uploads], **kwargs,
            )
        )

    def upload_cases(
        self,
        *,
        files: List[str],
        archive: str = None,
        reader_study: str = None,
        answer: str = None,
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
        answer
            The pk of the reader study answer to use.
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

        if answer is not None:
            upload_session_data["answer"] = answer

        if len(upload_session_data) != 1:
            raise ValueError(
                "One of archive, answer or reader_study can be set"
            )

        raw_image_upload_session = yield from self._upload_files(
            files=files, **upload_session_data
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
        alg = yield from self.__org_api_meta.algorithms.detail(slug=algorithm)
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
                    raw_image_upload_session = yield from self._upload_files(
                        files=value
                    )
                    i["upload_session"] = raw_image_upload_session["api_url"]
                elif isinstance(value, str):
                    i["image"] = value
            else:
                i["value"] = value
            job["inputs"].append(i)

        return (yield from self.__org_api_meta.algorithm_jobs.create(**job))
