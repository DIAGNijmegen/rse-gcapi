import os
from pathlib import Path
from time import sleep

import pytest
from requests import HTTPError

from gcapi import Client

RETINA_TOKEN = "f1f98a1733c05b12118785ffd995c250fe4d90da"
ADMIN_TOKEN = "1b9436200001f2eaf57cd77db075cbb60a49a00a"
ALGORITHMUSER_TOKEN = "dc3526c2008609b429514b6361a33f8516541464"
READERSTUDY_TOKEN = "01614a77b1c0b4ecd402be50a8ff96188d5b011d"


@pytest.mark.xfail(
    reason="Awaiting https://github.com/comic/grand-challenge.org/pull/1740"
)
@pytest.mark.parametrize(
    "annotation",
    [
        "retina_landmark_annotations",
        "retina_polygon_annotation_sets",
        "retina_single_polygon_annotations",
    ],
)
def test_list_annotations(local_grand_challenge, annotation):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    )
    response = getattr(c, annotation).list()
    assert len(response) == 0


@pytest.mark.xfail(
    reason="Awaiting https://github.com/comic/grand-challenge.org/pull/1740"
)
def test_create_landmark_annotation(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
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
        assert (
            sla_error["image"][0]
            == f'Invalid pk "{nil_uuid}" - object does not exist.'
        )


@pytest.mark.xfail(
    reason="Awaiting https://github.com/comic/grand-challenge.org/pull/1740"
)
def test_create_polygon_annotation_set(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    )
    nil_uuid = "00000000-0000-4000-9000-000000000000"
    create_data = {
        "grader": 0,
        "image": nil_uuid,
        "singlepolygonannotation_set": [
            {"z": 0, "value": [[0, 0], [1, 1], [2, 2]]},
            {"z": 1, "value": [[0, 0], [1, 1], [2, 2]]},
        ],
    }
    with pytest.raises(HTTPError) as e:
        c.retina_polygon_annotation_sets.create(**create_data)
    response = e.value.response
    assert response.status_code == 400
    response = response.json()
    assert response["grader"][0] == 'Invalid pk "0" - object does not exist.'
    assert (
        response["image"][0]
        == f'Invalid pk "{nil_uuid}" - object does not exist.'
    )
    assert response["name"][0] == "This field is required."


@pytest.mark.xfail(
    reason="Awaiting https://github.com/comic/grand-challenge.org/pull/1740"
)
def test_create_single_polygon_annotations(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    )
    create_data = {
        "z": 0,
        "value": [[0, 0], [1, 1], [2, 2]],
        "annotation_set": 0,
    }

    with pytest.raises(HTTPError) as e:
        c.retina_single_polygon_annotations.create(**create_data)
    response = e.value.response
    assert response.status_code == 400
    response = response.json()
    assert (
        response["annotation_set"][0]
        == 'Invalid pk "0" - object does not exist.'
    )


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
    c_admin = Client(
        token=ADMIN_TOKEN, base_url=local_grand_challenge, verify=False
    )
    existing_chunks_admin = c_admin(path="chunked-uploads/")["count"]
    c_admin.chunked_uploads.upload_file(file_to_upload)
    assert (
        c_admin(path="chunked-uploads/")["count"] == 1 + existing_chunks_admin
    )

    # retina
    c_retina = Client(
        token=RETINA_TOKEN, base_url=local_grand_challenge, verify=False
    )
    existing_chunks_retina = c_retina(path="chunked-uploads/")["count"]
    c_retina.chunked_uploads.upload_file(file_to_upload)
    assert (
        c_retina(path="chunked-uploads/")["count"]
        == 1 + existing_chunks_retina
    )

    c = Client(token="whatever")
    with pytest.raises(HTTPError):
        c.chunked_uploads.upload_file(file_to_upload)


@pytest.mark.parametrize(
    "files",
    (["image10x10x101.mha"], ["image10x10x10.mhd", "image10x10x10.zraw"]),
)
def test_upload_cases(local_grand_challenge, files):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    us = c.upload_cases(
        reader_study="reader-study",
        files=[Path(__file__).parent / "testdata" / f for f in files],
    )

    for _ in range(60):
        us = c.raw_image_upload_sessions.detail(us["pk"])
        if us["status"] == "Succeeded":
            break
        else:
            sleep(0.5)
    else:
        raise TimeoutError

    # Check that only one image was created
    assert len(us["image_set"]) == 1
    image = c(url=us["image_set"][0])

    # And that it was added to the reader study
    assert len(image["reader_study_set"]) == 1
    reader_study = c(url=image["reader_study_set"][0])
    assert reader_study["slug"] == "reader-study"
