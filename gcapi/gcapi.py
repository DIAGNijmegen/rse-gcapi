# -*- coding: utf-8 -*-
from __future__ import print_function, division, absolute_import

import json
import os
import sys
import uuid

import jsonschema

try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin

from requests import Session


def is_uuid(s):
    try:
        uuid.UUID(s)
    except ValueError:
        return False
    else:
        return True


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
        os.path.dirname(os.path.abspath(__file__)), "schemas", filename)

    try:
        with open(filename, "r") as f:
            jsn = json.load(f)
        return jsonschema.Draft7Validator(jsn)
    except ValueError as e:
        # I want missing/failing json imports to be an import error because that
        # is what they should indicate: a "broken" library
        raise ImportError("Json schema '{file}' cannot be loaded: {error}".format(
            file=filename, error=e))


class APIBase:
    _client = None  # type: Client
    base_path = ""
    sub_apis = {}

    json_schema = None

    def __init__(self, client):
        if isinstance(self, ModifiableMixin):
            ModifiableMixin.__init__(self)

        self._client = client

        for k, api in self.sub_apis.items():
            setattr(self, k, api(self._client))

    def __verify_against_schema(self, value):
        if self.json_schema is not None:
            self.json_schema.validate(value)

    def page(self, offset=0, limit=100):
        result = self._client(
            method="GET", path=self.base_path, params={"offset": offset, "limit": limit}
        )["results"]
        for i in result:
            self.__verify_against_schema(i)
        return result

    def iterate_all(self):
        REQ_COUNT = 100
        offset = 0
        while True:
            current_list = self.page(offset=offset, limit=REQ_COUNT)
            if len(current_list) == 0:
                break
            for item in current_list:
                yield item
            offset += REQ_COUNT

    def detail(self, pk):
        result = self._client(method="GET", path=urljoin(self.base_path, pk + "/"))
        self.__verify_against_schema(result)
        return result


class ModifiableMixin:
    _client = None  # type: Client

    modify_json_schema = None # type: jsonschema.Draft7Validator

    def __init__(self):
        pass

    def _process_post_arguments(self, post_args):
        if self.modify_json_schema is not None:
            self.modify_json_schema.validate(post_args)

    def send(self, **kwargs):
        self._process_post_arguments(kwargs)
        self._client(
            method="POST",
            path=self.base_path,
            json=kwargs,
        )


class ImagesAPI(APIBase):
    base_path = "cases/images/"


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
                urljoin(self._client.base_url, ReaderStudyQuestionsAPI.base_path),
                post_args["question"] + "/",
            )

        ModifiableMixin._process_post_arguments(self, post_args)


class ReaderStudiesAPI(APIBase):
    base_path = "reader-studies/"
    json_schema = import_json_schema("reader-study.json")

    sub_apis = {"answers": ReaderStudyAnswersAPI, "questions": ReaderStudyQuestionsAPI}

    answers = None  # type: ReaderStudyAnswersAPI
    questions = None  # type: ReaderStudyQuestionsAPI


class Client(Session):
    def __init__(
            self, token=None, base_url="https://grand-challenge.org/api/v1/",
            verify=True):
        super(Client, self).__init__()

        self.headers.update({"Accept": "application/json"})

        if token:
            self.headers.update({"Authorization": "TOKEN {}".format(token)})
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

    @property
    def base_url(self):
        return self._base_url

    def _validate_url(self, url):
        if not url.startswith(self._base_url):
            raise RuntimeError("{} does not start with {}".format(url, self._base_url))

    def __call__(self,
            method="GET", url="", path="", params=None,
            json=None, extra_headers=None):
        if not url:
            url = urljoin(self._base_url, path)
        if extra_headers is None:
            extra_headers = None
        if json is not None:
            extra_headers["Content-Type"] = "application/json"

        self._validate_url(url)

        response = self.request(
            method=method,
            url=url,
            headers=dict(dict(self.headers).items() + dict(extra_headers).items()),
            verify=self._verify,
            params={} if params is None else params,
            json=json,
        )

        response.raise_for_status()
        return response.json()
