import asyncio
import atexit
import inspect
import logging
import os
import threading
import uuid
import weakref
from builtins import StopAsyncIteration
from json import load
from random import randint
from time import sleep
from typing import (
    Any,
    Dict,
    List,
    AsyncIterable,
    AsyncIterator,
    Optional,
    Callable,
)
from urllib.parse import urljoin

import jsonschema
from httpx import HTTPStatusError

from .apibase import APIBase, ModifiableMixin
from .client import ClientBase

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

    async def ground_truth(self, pk, case_pk):
        result = await self._client(
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

    async def create(self, *, filename):
        return await self._client(
            method="POST",
            path=self.base_path,
            json={"filename": str(filename)},
        )

    async def generate_presigned_urls(self, *, pk, s3_upload_id, part_numbers):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/generate-presigned-urls/"
        )
        return await self._client(
            method="PATCH", path=url, json={"part_numbers": part_numbers}
        )

    async def abort_multipart_upload(self, *, pk, s3_upload_id):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/abort-multipart-upload/"
        )
        return await self._client(method="PATCH", path=url)

    async def complete_multipart_upload(self, *, pk, s3_upload_id, parts):
        url = urljoin(
            self.base_path, f"{pk}/{s3_upload_id}/complete-multipart-upload/"
        )
        return await self._client(
            method="PATCH", path=url, json={"parts": parts}
        )

    async def list_parts(self, *, pk, s3_upload_id):
        url = urljoin(self.base_path, f"{pk}/{s3_upload_id}/list-parts/")
        return await self._client(path=url)

    async def upload_fileobj(self, *, fileobj, filename):
        user_upload = await self.create(filename=filename)

        pk = user_upload["pk"]
        s3_upload_id = user_upload["s3_upload_id"]

        try:
            parts = await self._put_fileobj(
                fileobj=fileobj, pk=pk, s3_upload_id=s3_upload_id
            )
        except Exception:
            await self.abort_multipart_upload(pk=pk, s3_upload_id=s3_upload_id)
            raise

        return await self.complete_multipart_upload(
            pk=pk, s3_upload_id=s3_upload_id, parts=parts
        )

    async def _put_fileobj(self, *, fileobj, pk, s3_upload_id):
        part_number = 1  # s3 uses 1-indexed chunks
        presigned_urls = {}
        parts = []

        while True:
            chunk = fileobj.read(self.chunk_size)

            if not chunk:
                break

            if str(part_number) not in presigned_urls:
                presigned_urls.update(
                    await self._get_next_presigned_urls(
                        pk=pk,
                        s3_upload_id=s3_upload_id,
                        part_number=part_number,
                    )
                )

            response = await self._put_chunk(
                chunk=chunk, url=presigned_urls[str(part_number)]
            )

            parts.append(
                {"ETag": response.headers["ETag"], "PartNumber": part_number}
            )

            part_number += 1

        return parts

    async def _get_next_presigned_urls(self, *, pk, s3_upload_id, part_number):
        response = await self.generate_presigned_urls(
            pk=pk,
            s3_upload_id=s3_upload_id,
            part_numbers=[
                *range(part_number, part_number + self.n_presigned_urls)
            ],
        )
        return response["presigned_urls"]

    async def _put_chunk(self, *, chunk, url):
        num_retries = 0
        e = Exception

        while num_retries < self.max_retries:
            try:
                result = await self._client.request(
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


class AsyncClient(ClientBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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

    async def _upload_files(self, *, files, **kwargs):
        uploads = []
        for file in files:
            with open(file, "rb") as f:
                uploads.append(
                    await self.uploads.upload_fileobj(
                        fileobj=f, filename=file.name
                    )
                )

        raw_image_upload_session = await self.raw_image_upload_sessions.create(
            uploads=[u["api_url"] for u in uploads], **kwargs,
        )

        return raw_image_upload_session

    async def upload_cases(
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

        raw_image_upload_session = await self._upload_files(
            files=files, **upload_session_data
        )

        return raw_image_upload_session

    async def run_external_job(
        self, *, algorithm: str, inputs: Dict[str, Any]
    ):
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
        alg = await self.algorithms.detail(slug=algorithm)
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
                    raw_image_upload_session = await self._upload_files(
                        files=value
                    )
                    i["upload_session"] = raw_image_upload_session["api_url"]
                elif isinstance(value, str):
                    i["image"] = value
            else:
                i["value"] = value
            job["inputs"].append(i)

        return await self.algorithm_jobs.create(**job)


def make_sync(coroutinefunction) -> Callable:
    if inspect.isasyncgenfunction(coroutinefunction):

        def wrap(*args, **kwargs):
            loop = asyncio.get_event_loop()

            async_iterator: AsyncIterator[Any] = coroutinefunction(
                *args, **kwargs
            )
            try:
                while True:
                    yield loop.run_until_complete(async_iterator.__anext__())
            except StopAsyncIteration:
                pass

    else:

        def wrap(*args, **kwargs):
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(coroutinefunction(*args, **kwargs))

    return wrap


class Client:
    UNCLOSED_ASYNC_CLIENTS_LOCK = threading.RLock()
    UNCLOSED_ASYNC_CLIENTS: List["Client"] = []

    @classmethod
    def force_close_open_async_clients(cls):
        """
        Immediately closes all created async clients created for servicing
        synchronous clients. Generally, should not be called by a user as
        it invalidates all open Clients.
        """
        with cls.UNCLOSED_ASYNC_CLIENTS_LOCK:
            for client in tuple(cls.UNCLOSED_ASYNC_CLIENTS):
                client.close()
            del cls.UNCLOSED_ASYNC_CLIENTS[:]

    __async_client: AsyncClient

    def __init__(self, *args, **kwargs):
        self.__async_client = AsyncClient(*args, **kwargs)
        with self.UNCLOSED_ASYNC_CLIENTS_LOCK:
            self.UNCLOSED_ASYNC_CLIENTS.append(self)

        self._auth_header = self.__async_client._auth_header
        self.headers = self.__async_client.headers

        def wrap_api(base: APIBase):
            new_attrs = {}

            for name in dir(base):
                if name.startswith("_"):
                    continue
                item = getattr(base, name)
                if isinstance(item, APIBase):
                    new_attrs[name] = wrap_api(item)
                elif inspect.isasyncgenfunction(item):
                    new_attrs[name] = staticmethod(make_sync(item))
                elif inspect.iscoroutinefunction(item):
                    new_attrs[name] = staticmethod(make_sync(item))
                elif callable(item):
                    new_attrs[name] = staticmethod(item)
                else:
                    new_attrs[name] = item

            return type(f"Synchronized{type(base).__name__}", (), new_attrs)()

        for name in dir(self.__async_client):
            item = getattr(self.__async_client, name)
            if not isinstance(item, APIBase):
                continue

            setattr(self, name, wrap_api(item))

    @make_sync
    async def close(self):
        with self.UNCLOSED_ASYNC_CLIENTS_LOCK:
            await self.__async_client.aclose()
            self.UNCLOSED_ASYNC_CLIENTS.remove(self)

    @property
    def base_url(self):
        return self.__async_client.base_url

    def validate_url(self, *args, **kwargs):
        self.__async_client.validate_url(*args, **kwargs)

    @make_sync
    async def __call__(self, *args, **kwargs):
        return await self.__async_client(*args, **kwargs)

    @make_sync
    async def run_external_job(self, *args, **kwargs):
        return await self.__async_client.run_external_job(*args, **kwargs)

    @make_sync
    async def upload_cases(self, *args, **kwargs):
        return await self.__async_client.upload_cases(*args, **kwargs)


atexit.register(Client.force_close_open_async_clients)
