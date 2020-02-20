import itertools
import os
import uuid
from io import BytesIO
from json import load
from pathlib import Path
from random import randint, random
from time import sleep, time
from typing import Dict, List, Type
from urllib.parse import urljoin

import jsonschema
from requests import ConnectionError, Session


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


def load_input_data(input_file):
    with open(str(Path(__file__).parent / input_file), "rb") as f:
        return f.read()


def generate_new_upload_id(content):
    return "{}_{}_{}".format(hash(content), time(), random())


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
        with open(filename, "r") as f:
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
        )


class APIBase:
    _client = None  # type: Client
    base_path = ""
    sub_apis: Dict[str, Type["APIBase"]] = {}

    json_schema = None

    def __init__(self, client):
        if isinstance(self, ModifiableMixin):
            ModifiableMixin.__init__(self)

        self._client = client

        for k, api in list(self.sub_apis.items()):
            setattr(self, k, api(self._client))

    def _verify_against_schema(self, value):
        if self.json_schema is not None:
            self.json_schema.validate(value)

    def list(self):
        result = self._client(method="GET", path=self.base_path)
        for i in result:
            self._verify_against_schema(i)
        return result

    def page(self, offset=0, limit=100):
        result = self._client(
            method="GET",
            path=self.base_path,
            params={"offset": offset, "limit": limit},
        )["results"]
        for i in result:
            self._verify_against_schema(i)
        return result

    def iterate_all(self):
        req_count = 100
        offset = 0
        while True:
            current_list = self.page(offset=offset, limit=req_count)
            if len(current_list) == 0:
                break
            for item in current_list:
                yield item
            offset += req_count

    def detail(self, pk):
        result = self._client(
            method="GET", path=urljoin(self.base_path, pk + "/")
        )
        self._verify_against_schema(result)
        return result


class ModifiableMixin:
    _client = None  # type: Client

    modify_json_schema = None  # type: jsonschema.Draft7Validator

    def __init__(self):
        pass

    def _process_post_arguments(self, post_args):
        if self.modify_json_schema is not None:
            self.modify_json_schema.validate(post_args)

    def _validate_data(self, data):
        if data is None:
            data = {}
        self._process_post_arguments(data)
        return data

    def _execute_request(self, method, data, pk):
        url = (
            self.base_path
            if not pk
            else urljoin(self.base_path, str(pk) + "/")
        )
        return self._client(method=method, path=url, json=data)

    def perform_request(self, method, data=None, pk=False, validate=True):
        if validate:
            data = self._validate_data(data)
        return self._execute_request(method, data, pk)

    def send(self, **kwargs):
        # Created for backwards compatibility
        self.create(**kwargs)

    def create(self, **kwargs):
        return self.perform_request(
            "POST", data=kwargs, validate=kwargs.get("validate", True)
        )

    def update(self, pk, **kwargs):
        return self.perform_request("PUT", pk=pk, data=kwargs)

    def partial_update(self, pk, **kwargs):
        return self.perform_request("PATCH", pk=pk, data=kwargs)

    def delete(self, pk):
        return self.perform_request("DELETE", pk=pk, validate=False)


class ImagesAPI(APIBase):
    base_path = "cases/images/"


class UploadSessionFilesAPI(APIBase, ModifiableMixin):
    base_path = "cases/upload-sessions/files/"


class UploadSessionsAPI(APIBase, ModifiableMixin):
    base_path = "cases/upload-sessions/"

    def process_images(self, pk, json=None):
        url = urljoin(self.base_path, str(pk) + "/process_images/")
        return self._client(method="PATCH", path=url, json=json)


class WorkstationSessionsAPI(APIBase):
    base_path = "workstations/sessions/"


class ReaderStudyQuestionsAPI(APIBase):
    base_path = "reader-studies/questions/"


class ReaderStudyMineAnswersAPI(APIBase, ModifiableMixin):
    base_path = "reader-studies/answers/mine/"
    json_schema = import_json_schema("answer.json")


class ReaderStudyAnswersAPI(APIBase, ModifiableMixin):
    base_path = "reader-studies/answers/"
    json_schema = import_json_schema("answer.json")
    modify_json_schema = import_json_schema("post-answer.json")

    sub_apis = {"mine": ReaderStudyMineAnswersAPI}

    mine = None  # type: ReaderStudyMineAnswersAPI

    def _process_post_arguments(self, post_args):
        if is_uuid(post_args["question"]):
            post_args["question"] = urljoin(
                urljoin(
                    self._client.base_url, ReaderStudyQuestionsAPI.base_path
                ),
                post_args["question"] + "/",
            )

        ModifiableMixin._process_post_arguments(self, post_args)


class ReaderStudiesAPI(APIBase):
    base_path = "reader-studies/"
    json_schema = import_json_schema("reader-study.json")

    sub_apis = {
        "answers": ReaderStudyAnswersAPI,
        "questions": ReaderStudyQuestionsAPI,
    }

    answers = None  # type: ReaderStudyAnswersAPI
    questions = None  # type: ReaderStudyQuestionsAPI


class AlgorithmsAPI(APIBase):
    base_path = "algorithms/"


class AlgorithmResultsAPI(APIBase):
    base_path = "algorithms/results/"


class AlgorithmJobsAPI(APIBase):
    base_path = "algorithms/jobs/"


class RetinaLandmarkAnnotationSetsAPI(APIBase, ModifiableMixin):
    base_path = "retina/landmark-annotation/"
    json_schema = import_json_schema("landmark-annotation.json")
    modify_json_schema = import_json_schema("post-landmark-annotation.json")

    def for_image(self, pk):
        result = self._client(
            method="GET", path=self.base_path, params={"image_id": pk}
        )
        for i in result:
            self._verify_against_schema(i)
        return result


class ChunkedUploadsAPI(APIBase):
    base_path = "chunked-uploads/"

    def _upload_file_with_exponential_backoff(self, file_info):
        """
        Uploads a chunk with an exponential backoff retry strategy. The
        maximum number of attempts is 3.

        Parameters
        ----------
        file_info: dict
        Contains information about the chunk, start_byte, end_byte and upload_id.

        Raises
        ------
        ConnectionError
            Raised if the chunk cannot be uploaded within 3 attempts.
        """
        num_retries = 0
        e = Exception
        while num_retries < 3:
            try:
                result = self._client(
                    method="POST",
                    path=self.base_path,
                    files={file_info["filename"]: BytesIO(file_info["chunk"])},
                    data={
                        "filename": file_info["filename"],
                        "X-Upload-ID": file_info["upload_id"],
                    },
                    extra_headers={
                        "Content-Range": "bytes {}-{}/{}".format(
                            file_info["start_byte"],
                            file_info["end_byte"] - 1,
                            len(file_info["content"]),
                        )
                    },
                )
                break
            except ConnectionError as _e:
                num_retries += 1
                e = _e
                sleep((2 ** num_retries) + (randint(0, 1000) / 1000))
        else:
            raise e

        return result

    def upload_file(self, filename):
        """
        Uploads a file in chunks using rest api.

        Parameters
        ----------
        filename: str
            The name of the file to be uploaded.

        Raises
        ------
        ConnectionError
            Raised if a chunk cannot be uploaded.
        """

        content = load_input_data(filename)
        upload_id = generate_new_upload_id(content)
        start_byte = 0
        content_io = BytesIO(content)
        max_chunk_length = 2 ** 23
        results = []

        while True:
            chunk = content_io.read(max_chunk_length)

            if not chunk:
                break

            end_byte = start_byte + len(chunk)

            try:
                result = self._upload_file_with_exponential_backoff(
                    {
                        "start_byte": start_byte,
                        "end_byte": end_byte,
                        "chunk": chunk,
                        "content": content,
                        "upload_id": upload_id,
                        "filename": str(filename),
                    }
                )
            except ConnectionError as e:
                raise e

            results.append(result)

            start_byte += len(chunk)

        return list(itertools.chain(*results))


class WorkstationConfigsAPI(APIBase):
    base_path = "workstations/configs/"


class Client(Session):
    def __init__(
        self,
        token: str = "",
        base_url: str = "https://grand-challenge.org/api/v1/",
        verify: bool = True,
    ):
        super().__init__()

        self.headers.update({"Accept": "application/json"})

        if token:
            self.headers.update({"Authorization": f"TOKEN {token}"})
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
        self.chunked_uploads = ChunkedUploadsAPI(client=self)
        self.algorithms = AlgorithmsAPI(client=self)
        self.algorithm_results = AlgorithmResultsAPI(client=self)
        self.algorithm_jobs = AlgorithmJobsAPI(client=self)
        self.workstation_configs = WorkstationConfigsAPI(client=self)
        self.retina_landmark_annotations = RetinaLandmarkAnnotationSetsAPI(
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
        if not url.startswith(self._base_url):
            raise RuntimeError(f"{url} does not start with {self._base_url}")

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
            headers={**self.headers, **extra_headers},
            verify=self._verify,
            params={} if params is None else params,
            json=json,
        )
        response.raise_for_status()
        if response.headers.get("Content-Type") == "application/json":
            return response.json()
        else:
            return response

    def run_external_algorithm(
        self, algorithm_name: str, files_to_upload: List[str]
    ) -> Dict:
        """
        This function uploads an input image to grand challenge and runs an
        already uploaded algorithm which the user has access to. If the upload
        is finished correctly, grand challenge will automatically submit a job
        which you can access via AlgorithmJobsAPI.

        After the job is finished successfully the result will be available via
        AlgorithmResultsAPI.

        Parameters
        ----------
        algorithm_name:
            Title of the algorithm which has already been uploaded.
        files_to_upload:
            List of files to upload.

        Returns
        -------
        upload_session:
        This can be used to construct a query like
        /api/v1/cases/images/?origin=upload_session["pk"]
        to find out which Image did this RawImageUploadSession give rise to.
        This can be further used to identify the submitted job.
        """
        algorithm_image = self._get_latest_algorithm_image(algorithm_name)

        raw_image_upload_session = self.raw_image_upload_sessions.create(
            algorithm_image=algorithm_image
        )

        uploaded_files = {}
        for file in files_to_upload:
            uploaded_chunks = self.chunked_uploads.upload_file(file)
            uploaded_files.update(
                {c["uuid"]: c["filename"] for c in uploaded_chunks}
            )

        for file_id, filename in uploaded_files.items():
            self.raw_image_upload_session_files.create(
                upload_session=raw_image_upload_session["api_url"],
                staged_file_id=file_id,
                filename=filename,
            )

        self.raw_image_upload_sessions.process_images(
            pk=raw_image_upload_session["pk"]
        )

        return raw_image_upload_session

    def _get_latest_algorithm_image(self, algorithm_name: str) -> Dict:
        """Get the latest algorithm image for the given algorithm name. """
        algorithms = [
            a
            for a in self.algorithms.list()["results"]
            if a["title"] == algorithm_name
        ]

        if len(algorithms) != 1:
            raise ValueError(
                "{} is not found in available list of algorithms".format(
                    algorithm_name
                )
            )

        if not algorithms[0]["latest_ready_image"]:
            raise ValueError(f"{algorithm_name} is not ready to be used")

        algorithm_image = algorithms[0]["latest_ready_image"]

        return algorithm_image
