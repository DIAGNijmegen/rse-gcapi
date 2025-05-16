import logging
import os
import re
import uuid
from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from random import randint
from time import sleep
from typing import TYPE_CHECKING, Any, Callable, Optional, Union, cast
from urllib.parse import urljoin

import httpx
from httpx import URL, HTTPStatusError, Timeout

import gcapi.models
from gcapi.apibase import APIBase, ClientInterface, ModifiableMixin
from gcapi.check_version import check_version
from gcapi.create_strategies import Empty, SocketValueCreateStrategy
from gcapi.exceptions import ObjectNotFound
from gcapi.retries import BaseRetryStrategy, SelectiveBackoffStrategy
from gcapi.sync_async_hybrid_support import CapturedCall, mark_generator
from gcapi.typing import SocketValueSet

logger = logging.getLogger(__name__)


def is_uuid(s):
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
        filename: Union[str, Path],  # extension is added automatically
        image_type: Optional[
            str
        ] = None,  # restrict download to a particular image type
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
                image = yield from self.detail(api_url=url)
            else:
                image = yield from self.detail(**params)

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

            data = (
                yield self.yield_request(
                    method="GET", url=file.file, follow_redirects=True
                )
            ).content

            suffix = file.file.split(".")[-1]
            local_file = directory / f"{basename}.{suffix}"
            with local_file.open("wb") as fp:
                fp.write(data)

            downloaded_files.append(local_file)

        return downloaded_files


class UploadSessionsAPI(
    ModifiableMixin, APIBase[gcapi.models.RawImageUploadSession]
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
    ModifiableMixin, APIBase[gcapi.models.ReaderStudy]
):
    base_path = "reader-studies/answers/mine/"
    model = gcapi.models.ReaderStudy
    response_model = gcapi.models.Answer


class ReaderStudyAnswersAPI(ModifiableMixin, APIBase[gcapi.models.Answer]):
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

        return ModifiableMixin._process_request_arguments(self, data)


class ReaderStudyDisplaySetsAPI(
    ModifiableMixin, APIBase[gcapi.models.DisplaySet]
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

    def ground_truth(self, pk, case_pk):
        return (
            yield self.yield_request(
                method="GET",
                path=urljoin(
                    self.base_path, pk + "/ground-truth/" + case_pk + "/"
                ),
            )
        )


class AlgorithmsAPI(APIBase[gcapi.models.Algorithm]):
    base_path = "algorithms/"
    model = gcapi.models.Algorithm


class AlgorithmJobsAPI(ModifiableMixin, APIBase[gcapi.models.HyperlinkedJob]):
    base_path = "algorithms/jobs/"
    model = gcapi.models.HyperlinkedJob
    response_model = gcapi.models.JobPost

    @mark_generator
    def by_input_image(self, pk):
        yield from self.iterate_all(params={"image": pk})


class ArchivesAPI(APIBase[gcapi.models.Archive]):
    base_path = "archives/"
    model = gcapi.models.Archive


class ArchiveItemsAPI(ModifiableMixin, APIBase[gcapi.models.ArchiveItem]):
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

    def create(self, *, filename):
        result = yield self.yield_request(
            method="POST",
            path=self.base_path,
            json={"filename": str(filename)},
        )
        return self.model(**result)

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

        pk = user_upload.pk
        s3_upload_id = user_upload.s3_upload_id

        try:
            parts = yield from self._put_fileobj(
                fileobj=fileobj, pk=pk, s3_upload_id=s3_upload_id
            )
        except Exception:
            yield from self.abort_multipart_upload(
                pk=pk, s3_upload_id=s3_upload_id
            )
            raise

        result = yield from self.complete_multipart_upload(
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
    archives: ArchivesAPI
    workstation_configs: WorkstationConfigsAPI
    raw_image_upload_sessions: UploadSessionsAPI
    archive_items: ArchiveItemsAPI
    interfaces: ComponentInterfacesAPI


class ClientBase(ApiDefinitions, ClientInterface):
    # Make MyPy happy, this is a mixin now, so the dependent values will
    # come in through a side-channel
    if TYPE_CHECKING:
        _Base = httpx.Client

    _api_meta: ApiDefinitions
    __org_api_meta: ApiDefinitions

    from gcapi.typing import SocketValueSet, SocketValueSetDescription

    def __init__(
        self,
        init_base_cls: Union[httpx.Client, httpx.AsyncClient],
        transport_cls: Union[httpx.HTTPTransport, httpx.AsyncHTTPTransport],
        token: str = "",
        base_url: str = "https://grand-challenge.org/api/v1/",
        verify: bool = True,
        timeout: float = 60.0,
        retry_strategy: Optional[Callable[[], BaseRetryStrategy]] = None,
    ):
        check_version(base_url=base_url)

        retry_strategy = retry_strategy or SelectiveBackoffStrategy(
            backoff_factor=0.1,
            maximum_number_of_retries=8,  # ~25.5 seconds total backoff
        )
        init_base_cls.__init__(
            self,
            verify=verify,
            timeout=Timeout(timeout=timeout),
            transport=transport_cls(
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
                f"'ClientBase' has no function or API {item!r}"
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

    def _upload_image_files(self, *, files, **kwargs):
        uploads = []
        for file in files:
            with open(file, "rb") as f:
                uploads.append(
                    (
                        yield from self.__org_api_meta.uploads.upload_fileobj(
                            fileobj=f, filename=os.path.basename(file)
                        )
                    )
                )

        return (
            yield from self.__org_api_meta.raw_image_upload_sessions.create(
                uploads=[u.api_url for u in uploads], **kwargs
            )
        )

    def _upload_file(self, value):
        with open(value[0], "rb") as f:
            upload = yield from self.__org_api_meta.uploads.upload_fileobj(
                fileobj=f, filename=value[0].name
            )
        return upload

    def upload_cases(  # noqa: C901
        self,
        *,
        files: list[str],
        archive: Optional[str] = None,
        answer: Optional[str] = None,
        archive_item: Optional[str] = None,
        display_set: Optional[str] = None,
        interface: Optional[str] = None,
    ):
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
        Parameters
        ----------
        files
            The list of files on disk that form 1 Image. These can be a set of
            .mha, .mhd, .raw, .zraw, .dcm, .nii, .nii.gz, .tiff, .png, .jpeg,
            .jpg, .svs, .vms, .vmu, .ndpi, .scn, .mrxs and/or .bif files.
        archive
            The slug of the archive to use.
        archive_item
            The pk of the archive item to use.
        answer
            The pk of the reader study answer to use.
        display_set
            The pk of the display set to use.
        interface
            The slug of the interface to use. Can only be defined for archive
            and archive item uploads.
        Returns
        -------
            The created upload session.
        """
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

        raw_image_upload_session = yield from self._upload_image_files(
            files=files, **upload_session_data
        )

        return raw_image_upload_session

    def run_external_job(  # noqa: C901
        self, *, algorithm: str, inputs: dict[str, Any]
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
        alg = yield from self.__org_api_meta.algorithms.detail(slug=algorithm)

        if len(alg.interfaces) > 1:
            raise NotImplementedError(
                "Support for algorithms with multiple interfaces are "
                "not currently supported by this method."
            )

        input_interfaces = {ci.slug: ci for ci in alg.interfaces[0]["inputs"]}

        for ci in input_interfaces:
            if (
                ci not in inputs
                and input_interfaces[ci]["default_value"] is None
            ):
                raise ValueError(f"{ci} is not provided")

        job = {"algorithm": alg.api_url, "inputs": []}
        for input_title, value in inputs.items():
            ci = input_interfaces.get(input_title, None)  # type: ignore
            if not ci:
                raise ValueError(
                    f"{input_title} is not an input interface for this algorithm"
                )

            i = {"interface": ci.slug}  # type: ignore
            if ci.super_kind.lower() == "image":  # type: ignore
                if isinstance(value, list):
                    raw_image_upload_session = (
                        yield from self._upload_image_files(files=value)
                    )
                    i["upload_session"] = raw_image_upload_session.api_url
                elif isinstance(value, str):
                    i["image"] = value
            elif ci["super_kind"].lower() == "file":  # type: ignore
                if len(value) != 1:
                    raise ValueError(
                        f"Only a single file can be provided for {ci['title']}."  # type: ignore
                    )
                upload = yield from self._upload_file(value)
                i["user_upload"] = upload.api_url
            else:
                i["value"] = value
            job["inputs"].append(i)  # type: ignore

        return (yield from self.__org_api_meta.algorithm_jobs.create(**job))

    def add_cases_to_reader_study(
        self, *, reader_study: str, display_sets: list[dict[str, Any]]
    ):
        """
        This function takes a reader study slug and a list of diplay sets
        and creates the provided display sets and adds them to the reader
        study. The format for the list of display sets is as follows:
        [
            {
                "slug_0": ["filepath_0", ...]
                ...
                "slug_n": {"json": "value"}

            },
            ...
        ]

        Where the file paths are local paths to the files making up a
        single image. For file type interface the file path can only
        contain a single file. For json type interfaces any value that
        is valid for the interface can be passed.`

        Parameters
        ----------
        reader_study
        display_sets

        Returns
        -------
        The pks of the newly created display sets.
        """
        res = []
        interfaces: dict[str, gcapi.models.ComponentInterface] = {}
        for display_set in display_sets:
            new_interfaces = yield from self._validate_display_set_values(
                display_set.items(), interfaces
            )
            interfaces.update(new_interfaces)

        for display_set in display_sets:
            ds = yield from self.__org_api_meta.reader_studies.display_sets.create(
                reader_study=reader_study
            )
            values = []
            for slug, value in display_set.items():
                interface = interfaces[slug]
                data = {"interface": slug}
                super_kind = interface.super_kind.casefold()
                if super_kind == "image":
                    yield from self._upload_image_files(
                        display_set=ds.pk, interface=slug, files=value
                    )
                    data = {}
                elif super_kind == "file":
                    upload = yield from self._upload_file(value)
                    data["user_upload"] = upload.api_url
                else:
                    data["value"] = value
                if data:
                    values.append(data)
            yield from self.__org_api_meta.reader_studies.display_sets.partial_update(
                pk=ds.pk, values=values
            )

            res.append(ds.pk)
        return res  # noqa: B901

    def update_archive_item(
        self, *, archive_item_pk: str, values: SocketValueSetDescription
    ):
        """
        This function updates an existing archive item with the provided values
        and returns the updated archive item.

        You can use this function, for example, to add metadata to an archive item.

        First, retrieve the archive items from your archive:

        archive = client.archives.detail(slug="...")
        items = list(
            client.archive_items.iterate_all(params={"archive": archive.pk})
        )

        To then add, for example, a PDF report and a lung volume
        value to the first archive item , provide the interface slugs together
        with the respective value or file path as follows:
        client.update_archive_item(
            archive_item_pk=items[0].id,
            values={
                "report": [...],
                "lung-volume": 1.9,
            },
        )
        If you provide a value or file for an existing interface of the archive
        item, the old value will be overwritten by the new one, hence allowing you
        to update existing archive item values.

        Parameters
        ----------
        archive_item_pk
        values

        Returns
        -------
        The updated archive item
        """
        item = yield from self.__org_api_meta.archive_items.detail(
            pk=archive_item_pk
        )
        return (
            yield from self._update_socket_value_set(
                target=item,
                description=values,
                api=self.__org_api_meta.archive_items,
            )
        )

    def add_cases_to_archive(
        self,
        *,
        archive: Union[str, gcapi.models.Archive],
        archive_items: list[SocketValueSetDescription],
    ):
        """
        This function takes an archive slug or model and a list of archive item
        descriptions and creates the archive item to be used on the platform.

        Parameters
        ----------
        archive
            slug for the archive (e.g. "i-am-an-archive"). You can find this
            readily in the URL you use to visit the archive page:

                https://grand-challenge.org/archives/i-am-an-archive/

        archive_items
            The format for the description of archive items is as follows:

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

            Where the file paths are local paths to the files making up a
            single image. For file type interfaces the file path can only
            reference a single file. For json type interfaces any value that
            is valid for the interface can directly be passed.

        Returns
        -------
        The pks of the newly created archive items.
        """

        if isinstance(archive, str):
            archive = yield from self.__org_api_meta.archives.detail(
                slug=archive
            )

        created_archive_items = yield from self._create_socket_value_sets(
            creation_kwargs={"archive": archive.api_url},
            descriptions=archive_items,
            api=self.__org_api_meta.archive_items,
        )

        return [ai.pk for ai in created_archive_items]

    def _fetch_socket_detail(
        self,
        slug_or_socket,
        cache=None,
        ref_url="https://grand-challenge.org/components/interfaces/reader-studies/",
    ):
        if isinstance(slug_or_socket, gcapi.models.ComponentInterface):
            return slug_or_socket
        else:
            slug = slug_or_socket

        if cache and slug in cache:
            return cache[slug]
        try:
            interface = yield from self.__org_api_meta.interfaces.detail(
                slug=slug
            )

            if cache:
                cache[slug] = interface

            return interface
        except ObjectNotFound as e:
            raise ValueError(
                f"{slug} is not an existing interface. "
                f"Please provide one from this list: "
                f"{ref_url}"
            ) from e

    def _create_socket_value_sets(
        self,
        *,
        creation_kwargs: dict,
        descriptions: list[SocketValueSetDescription],
        api: ModifiableMixin,
    ):
        interface_cache: dict[str, gcapi.models.ComponentInterface] = {}

        # Firstly, prepare ALL the strategies
        strategy_collections: list[list[SocketValueCreateStrategy]] = []
        for description in descriptions:
            strategy_per_value = []

            for socket_slug, source in description.items():
                socket: gcapi.models.ComponentInterface = (
                    yield from self._fetch_socket_detail(
                        slug_or_socket=socket_slug,
                        cache=interface_cache,
                    )
                )
                strategy = SocketValueCreateStrategy(
                    client=self,
                    socket=cast(gcapi.models.ComponentInterface, socket),
                    source=source,
                )
                strategy.prepare()
                strategy_per_value.append(strategy)

            strategy_collections.append(strategy_per_value)

        # Secondly, create + update socket-value sets
        socket_value_sets: list[SocketValueSet] = []
        for collection in strategy_collections:
            socket_value_set = yield from api.create(**creation_kwargs)
            values = []
            for strategy in collection:
                strategy.parent = socket_value_set
                post_value = yield from strategy()
                if post_value is not Empty:
                    values.append(post_value)
            update_socket_value_set = yield from api.partial_update(
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
                yield from self._fetch_socket_detail(socket_slug)
            )
            strategy = SocketValueCreateStrategy(
                source=source,
                socket=socket,
                client=self,
                parent=target,
            )
            yield from strategy.prepare()
            strategies.append(strategy)

        values = []
        for strategy in strategies:
            value = yield from strategy()
            if value is not Empty:
                values.append(value)

        return (  # noqa: B901
            yield from api.partial_update(pk=target.pk, values=values)
        )
