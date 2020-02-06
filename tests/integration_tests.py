import os
from time import sleep

import pytest
from requests import HTTPError

from gcapi import Client

RETINA_TOKEN = "f1f98a1733c05b12118785ffd995c250fe4d90da"
ADMIN_TOKEN = "1b9436200001f2eaf57cd77db075cbb60a49a00a"
ALGORITHMUSER_TOKEN = "dc3526c2008609b429514b6361a33f8516541464"


def test_list_landmark_annotations(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN)
    response = c.retina_landmark_annotations.list()
    assert len(response) == 0


def test_create_landmark_annotation(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN)
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
    c = Client(base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN)
    assert c.raw_image_upload_session_files.page() == []
    assert c.raw_image_upload_sessions.page() == []


def test_local_response(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN)
    # Empty response, but it didn't error out so the server is responding
    assert c.algorithms.page() == []


def test_chunked_uploads(local_grand_challenge):

    file_to_upload = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "testdata", "rnddata"
    )
    # admin
    c_admin = Client(token=ADMIN_TOKEN, base_url=local_grand_challenge, verify=False)
    existing_chunks_admin = c_admin(path="chunked-uploads/")["count"]
    c_admin.chunked_uploads.send(file_to_upload)
    assert c_admin(path="chunked-uploads/")["count"] == 1 + existing_chunks_admin

    # retina
    c_retina = Client(token=RETINA_TOKEN, base_url=local_grand_challenge, verify=False)
    existing_chunks_retina = c_retina(path="chunked-uploads/")["count"]
    c_retina.chunked_uploads.send(file_to_upload)
    assert c_retina(path="chunked-uploads/")["count"] == 1 + existing_chunks_retina

    c = Client(token="whatever")
    with pytest.raises(HTTPError):
        c.chunked_uploads.send(file_to_upload)


def test_run_external_algorithm(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=ALGORITHMUSER_TOKEN)
    existing_algoritm_jobs = c.algorithm_jobs.list()["count"]

    image_to_upload = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "testdata", "image10x10x101.mha"
    )
    assert c.algorithm_jobs.list()["count"] == existing_algoritm_jobs

    existing_upload_sessions_count = c.raw_image_upload_sessions.list()["count"]
    us_pk = c.run_external_algorithm("Test Algorithm", [image_to_upload])

    assert (
        c.raw_image_upload_sessions.list()["count"]
        == 1 + existing_upload_sessions_count
    )

    for _ in range(60):
        if (c.raw_image_upload_sessions.detail(us_pk)["status"]) == "Succeeded":
            break
        else:
            sleep(0.5)
    else:
        raise TimeoutError

    assert c.raw_image_upload_sessions.detail(us_pk)["status"] == "Succeeded"
    assert c.algorithm_jobs.list()["count"] == 1 + existing_algoritm_jobs
