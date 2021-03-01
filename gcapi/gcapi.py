import itertools
import os
import re
import uuid
from io import BytesIO
from json import load
from random import randint, random
from time import sleep, time
from typing import Dict, List, Type
from urllib.parse import urljoin, urlparse

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
    with open(input_file, "rb") as f:
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
            method="GET", path=self.base_path, params=params,
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

    def send(self, **kwargs):
        # Created for backwards compatibility
        self.create(**kwargs)

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

    def process_images(self, pk, json=None):
        url = urljoin(self.base_path, str(pk) + "/process_images/")
        return self._client(method="PATCH", path=url, json=json)


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
    validation_schemas = {
        "GET": import_json_schema("reader-study.json"),
    }

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


class AlgorithmJobsAPI(APIBase):
    base_path = "algorithms/jobs/"

    def by_input_image(self, pk):
        return self.iterate_all(params={"image": pk})


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

    def upload_file(self, filename, content=None):
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
        if not content:
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

        self.headers.update(
            {"Accept": "application/json", **self._auth_header(token=token)}
        )

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

    @staticmethod
    def _auth_header(token: str = "") -> Dict:
        if not token:
            try:
                token = str(os.environ["GRAND_CHALLENGE_AUTHORIZATION"])
            except KeyError:
                raise RuntimeError("Token must be set")

        token = re.sub(" +", " ", token)
        token_parts = token.strip().split(" ")

        if len(token_parts) not in [1, 2]:
            raise RuntimeError("Invalid token format")

        return {"Authorization": f"BEARER {token_parts[-1]}"}

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

    def upload_cases(
        self,
        *,
        files: List[str],
        algorithm: str = None,
        archive: str = None,
        reader_study: str = None,
    ):
        """
        Uploads a set of files to an algorithm, archive or reader study.

        A new upload session will be created on grand challenge to import and
        standardise your files. This function will return this new upload
        session object, that you can query for the import status. If this
        import is successful, the new images will then be added to the selected
        algorithm, archive, or reader study.

        You will need to provide the slugs of the objects to pass the images
        along to. You can find this in the url of the object that you want
        to use. For instance, if you want to use the algorithm at

            https://grand-challenge.org/algorithms/corads-ai/

        the slug for this is "corads-ai", so you would call this function with

            upload_cases(files=[...], algorithm="corads-ai")

        Parameters
        ----------
        files
            The list of files on disk that form 1 Image. These can be a set of
            .mha, .mhd, .raw, .zraw, .dcm, .nii, .nii.gz, .tiff, .png, .jpeg,
            .jpg, .svs, .vms, .vmu, .ndpi, .scn, .mrxs and/or .bif files.
        algorithm
            The slug of the algorithm to use.
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

        if algorithm is not None:
            upload_session_data["algorithm"] = algorithm

        if len(upload_session_data) != 1:
            raise ValueError(
                "Only one of algorithm, archive or reader_study should be set"
            )

        raw_image_upload_session = self.raw_image_upload_sessions.create()

        uploaded_files = {}
        for file in files:
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
            pk=raw_image_upload_session["pk"], json=upload_session_data
        )

        return raw_image_upload_session
