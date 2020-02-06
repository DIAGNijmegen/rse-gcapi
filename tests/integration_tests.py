import os

import pytest
from requests import HTTPError

from gcapi import Client


def test_list_landmark_annotations(local_grand_challenge):
    c = Client(
        base_url="https://gc.localhost/api/v1/",
        verify=False,
        token="f1f98a1733c05b12118785ffd995c250fe4d90da",  # retina token
    )
    response = c.retina_landmark_annotations.list()
    assert len(response) == 0


def test_create_landmark_annotation(local_grand_challenge):
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


def test_raw_image_and_upload_session(local_grand_challenge):
    c = Client(
        base_url="https://gc.localhost/api/v1/",
        verify=False,
        token="1b9436200001f2eaf57cd77db075cbb60a49a00a",  # admin token
    )
    assert c.raw_image_files.page() == []
    assert c.raw_image_upload_sessions.page() == []


def test_local_response(local_grand_challenge):
    c = Client(
        base_url="https://gc.localhost/api/v1/",
        verify=False,
        token="1b9436200001f2eaf57cd77db075cbb60a49a00a",
    )
    # Empty response, but it didn't error out so the server is responding
    assert c.algorithms.page() == []


def test_chunked_uploads(local_grand_challenge):
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
