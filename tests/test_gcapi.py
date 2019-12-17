#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `gcapi` package."""
import sys
import os
import pytest

from click.testing import CliRunner
from jsonschema import ValidationError
from requests.exceptions import HTTPError

from gcapi import Client
from gcapi import cli


def test_no_auth_exception():
    with pytest.raises(RuntimeError):
        Client()


def test_headers():
    token = "foo"
    c = Client(token=token)
    assert c.headers["Authorization"] == "TOKEN {}".format(token)
    assert c.headers["Accept"] == "application/json"


def test_http_base_url():
    with pytest.raises(RuntimeError):
        Client(token="foo", base_url="http://example.com")


def test_custom_base_url():
    c = Client(token="foo")
    assert c._base_url.startswith("https://grand-challenge.org")

    c = Client(token="foo", base_url="https://example.com")
    assert c._base_url.startswith("https://example.com")


def test_command_line_interface():
    """Test the CLI."""
    runner = CliRunner()
    result = runner.invoke(cli.main)
    assert result.exit_code == 0
    assert "gcapi.cli.main" in result.output
    help_result = runner.invoke(cli.main, ["--help"])
    assert help_result.exit_code == 0
    assert "--help  Show this message and exit." in help_result.output


@pytest.mark.skipif(sys.version_info >= (3, 0), reason="Testing a bug in Py2")
def test_mixed_string_and_unicode():
    c = Client(token="whatever")
    with pytest.raises(HTTPError):
        # The call should get here after calling urljoin
        c(path=unicode("dsfa"))


def test_chunked_uploads():
    file_to_upload = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "testdata", "rnddata"
    )
    # admin
    c_admin = Client(
        token="1b9436200001f2eaf57cd77db075cbb60a49a00a",
        base_url="https://gc.localhost/api/v1/",
        verify=False,
    )
    c_admin.chunked_uploads.send(file_to_upload)
    assert c_admin(path="chunked-uploads/")["count"] == 1

    # retina
    c_retina = Client(
        token="f1f98a1733c05b12118785ffd995c250fe4d90da",
        base_url="https://gc.localhost/api/v1/",
        verify=False,
    )
    c_retina.chunked_uploads.send(file_to_upload)
    assert c_retina(path="chunked-uploads/")["count"] == 1

    c = Client(token="whatever")
    with pytest.raises(HTTPError):
        c.chunked_uploads.send(file_to_upload)


def test_local_response():
    c = Client(
        base_url="https://gc.localhost/api/v1/",
        verify=False,
        token="1b9436200001f2eaf57cd77db075cbb60a49a00a",
    )
    # Empty response, but it didn't error out so the server is responding
    assert c.algorithms.page() == []


@pytest.mark.parametrize(
    "datetime_string,valid",
    (
        ("teststring", False),
        (1, False),
        ({}, False),
        ("2019-13-11T13:55:00.123456Z", False),
        ("2019-12-11T25:55:00.123456Z", False),
        ("2019-12-11T13:60:00.123456Z", False),
        ("2019-12-11T13:55:00.123456Z", True),
        ("2019-12-11T13:55:00Z", True),
    ),
)
def test_datetime_string_format_validation(datetime_string, valid):
    landmark_annotation = {
        "id": "4d5721f8-485d-4a17-8507-e06a8f897dd3",
        "grader": 7,
        "created": datetime_string,
        "singlelandmarkannotation_set": [
            {
                "id": "69ea96c2-9a96-4080-9b2c-0b9d0417dda1",
                "image": "70ec13fd-7fcf-4c84-bcd0-5fa3ac34a6b0",
                "landmarks": [
                    [249.029700179422, 194.950491966439],
                    [308.910901038675, 210.158411188267],
                    [270.891081357472, 353.683160558702],
                ],
            },
            {
                "id": "8055d041-d78d-4fa6-94af-1e57e80e11d8",
                "image": "46ba46f4-7fcd-418d-a43f-f668b286daeb",
                "landmarks": [
                    [759.567661360211, 495.505389057573],
                    [911.79182925945, 646.176269350096],
                    [672.582428997143, 726.948261175343],
                ],
            },
        ],
    }
    c = Client(
        base_url="https://gc.localhost/api/v1/",
        verify=False,
        token="f1f98a1733c05b12118785ffd995c250fe4d90da",  # retina token
    )
    if valid:
        assert (
            c.retina_landmark_annotations._verify_against_schema(landmark_annotation)
            is None
        )
    else:
        with pytest.raises(ValidationError):
            c.retina_landmark_annotations._verify_against_schema(landmark_annotation)


def test_list_landmark_annotations():
    c = Client(
        base_url="https://gc.localhost/api/v1/",
        verify=False,
        token="f1f98a1733c05b12118785ffd995c250fe4d90da",  # retina token
    )
    response = c.retina_landmark_annotations.list()
    len(response) == 0


def test_create_landmark_annotation():
    c = Client(
        base_url="https://gc.localhost/api/v1/",
        verify=False,
        token="f1f98a1733c05b12118785ffd995c250fe4d90da",  # retina token
    )
    nil_uuid = "00000000-0000-4000-9000-000000000000"
    create_data = {
        "grader": 0,
        "singlelandmarkannotation_set": [
            {"image": nil_uuid, "landmarks": [[0, 0], [1, 1], [2, 2]]},
            {"image": nil_uuid, "landmarks": [[0, 0], [1, 1], [2, 2]]},
        ],
    }
    with pytest.raises(HTTPError) as e:
        c.retina_landmark_annotations.create(**create_data)
    response = e.value.response
    assert response.status_code == 400
    response = response.json()
    assert response["grader"][0] == 'Invalid pk "0" - object does not exist.'
    for sla_error in response["singlelandmarkannotation_set"]:
        assert sla_error["image"][
            0
        ] == 'Invalid pk "{}" - object does not exist.'.format(nil_uuid)
