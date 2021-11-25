from io import BytesIO
from pathlib import Path
from time import sleep

import pytest
from httpx import HTTPStatusError

from gcapi import Client
from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound

RETINA_TOKEN = "f1f98a1733c05b12118785ffd995c250fe4d90da"
ADMIN_TOKEN = "1b9436200001f2eaf57cd77db075cbb60a49a00a"
READERSTUDY_TOKEN = "01614a77b1c0b4ecd402be50a8ff96188d5b011d"
DEMO_PARTICIPANT_TOKEN = "00aa710f4dc5621a0cb64b0795fbba02e39d7700"


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
    with pytest.raises(HTTPStatusError) as e:
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
    with pytest.raises(HTTPStatusError) as e:
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


def test_create_single_polygon_annotations(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    )
    create_data = {
        "z": 0,
        "value": [[0, 0], [1, 1], [2, 2]],
        "annotation_set": 0,
    }

    with pytest.raises(HTTPStatusError) as e:
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
    assert c.raw_image_upload_sessions.page() == []


def test_local_response(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN)
    # Empty response, but it didn't error out so the server is responding
    assert c.algorithms.page() == []


def test_chunked_uploads(local_grand_challenge):
    file_to_upload = Path(__file__).parent / "testdata" / "rnddata"

    # admin
    c_admin = Client(
        token=ADMIN_TOKEN, base_url=local_grand_challenge, verify=False
    )
    existing_chunks_admin = c_admin(path="uploads/")["count"]

    with open(file_to_upload, "rb") as f:
        c_admin.uploads.upload_fileobj(fileobj=f, filename=file_to_upload.name)

    assert c_admin(path="uploads/")["count"] == 1 + existing_chunks_admin

    # retina
    c_retina = Client(
        token=RETINA_TOKEN, base_url=local_grand_challenge, verify=False
    )
    existing_chunks_retina = c_retina(path="uploads/")["count"]

    with open(file_to_upload, "rb") as f:
        c_retina.uploads.upload_fileobj(
            fileobj=f, filename=file_to_upload.name
        )

    assert c_retina(path="uploads/")["count"] == 1 + existing_chunks_retina

    c = Client(token="whatever")
    with pytest.raises(HTTPStatusError):
        with open(file_to_upload, "rb") as f:
            c.uploads.upload_fileobj(fileobj=f, filename=file_to_upload.name)


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
    rs = next(c.reader_studies.iterate_all(params={"slug": "reader-study"}))
    rs_images = c.images.iterate_all(params={"reader_study": rs["pk"]})
    assert image["pk"] in [im["pk"] for im in rs_images]

    # And that we can download it
    response = c(url=image["files"][0]["file"], follow_redirects=True)
    assert response.status_code == 200


@pytest.mark.parametrize("files", (["image10x10x101.mha"],))
def test_download_cases(local_grand_challenge, files, tmpdir):
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

    # Check that we can download the uploaded image
    tmpdir = Path(tmpdir)
    downloaded_files = c.images.download(
        filename=tmpdir / "image", url=us["image_set"][0]
    )
    assert len(downloaded_files) == 1

    # Check that the downloaded file is a mha file
    with downloaded_files[0].open("rb") as fp:
        line = fp.readline().decode("ascii").strip()
    assert line == "ObjectType = Image"


@pytest.mark.parametrize("files", (["image10x10x101.mha"],))
def test_create_job_with_upload(local_grand_challenge, files):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )

    job = c.run_external_job(
        algorithm="test-algorithm-evaluation-1",
        inputs={
            "generic-medical-image": [
                Path(__file__).parent / "testdata" / f for f in files
            ]
        },
    )
    assert job["status"] == "Queued"
    assert len(job["inputs"]) == 1
    job = c.algorithm_jobs.detail(job["pk"])
    assert job["status"] == "Queued"


def test_get_algorithm_by_slug(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )

    by_slug = c.algorithms.detail(slug="test-algorithm-evaluation-1")
    by_pk = c.algorithms.detail(pk=by_slug["pk"])

    assert by_pk == by_slug


def test_get_reader_study_by_slug(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN,
    )

    by_slug = c.reader_studies.detail(slug="reader-study")
    by_pk = c.reader_studies.detail(pk=by_slug["pk"])

    assert by_pk == by_slug


@pytest.mark.parametrize("key", ["slug", "pk"])
def test_detail_no_objects(local_grand_challenge, key):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN,
    )

    with pytest.raises(ObjectNotFound):
        c.reader_studies.detail(**{key: "foo"})


def test_detail_multiple_objects(local_grand_challenge):
    c = Client(token=ADMIN_TOKEN, base_url=local_grand_challenge, verify=False)

    c.uploads.upload_fileobj(fileobj=BytesIO(b"123"), filename="test")
    c.uploads.upload_fileobj(fileobj=BytesIO(b"456"), filename="test")

    with pytest.raises(MultipleObjectsReturned):
        c.uploads.detail(slug="")


def test_auth_headers_not_sent():
    c = Client(token="foo")
    response = c.uploads._put_chunk(
        chunk=BytesIO(b"123"), url="https://httpbin.org/put"
    )
    sent_headers = response.json()["headers"]
    assert not set(c._auth_header.keys()) & set(sent_headers.keys())
