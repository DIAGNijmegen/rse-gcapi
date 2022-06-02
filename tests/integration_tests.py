from io import BytesIO
from pathlib import Path

import pytest
from httpx import HTTPStatusError

from gcapi import Client
from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound
from tests.utils import recurse_call

RETINA_TOKEN = "f1f98a1733c05b12118785ffd995c250fe4d90da"
ADMIN_TOKEN = "1b9436200001f2eaf57cd77db075cbb60a49a00a"
READERSTUDY_TOKEN = "01614a77b1c0b4ecd402be50a8ff96188d5b011d"
DEMO_PARTICIPANT_TOKEN = "00aa710f4dc5621a0cb64b0795fbba02e39d7700"
ARCHIVE_TOKEN = "0d284528953157759d26c469297afcf6fd367f71"


@recurse_call
def get_upload_session(client, upload_pk):
    upl = client.raw_image_upload_sessions.detail(upload_pk)
    if upl["status"] != "Succeeded":
        raise ValueError
    return upl


@recurse_call
def get_image(client, image_url):
    return client(url=image_url)


@recurse_call
def get_archive_items(client, archive_pk, min_size):
    items = list(
        client.archive_items.iterate_all(params={"archive": archive_pk})
    )
    if len(items) <= min_size:
        raise ValueError
    return items


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


@pytest.mark.parametrize(
    "files",
    (
        # Path based
        [Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        # str based
        [str(Path(__file__).parent / "testdata" / "image10x10x101.mha")],
        # mixed str and Path
        [
            str(Path(__file__).parent / "testdata" / "image10x10x10.mhd"),
            Path(__file__).parent / "testdata" / "image10x10x10.zraw",
        ],
    ),
)
def test_input_types_upload_cases(local_grand_challenge, files):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    c.upload_cases(archive="archive", files=files)


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
    "files, interface",
    (
        (["image10x10x101.mha"], "generic-overlay"),
        (["image10x10x101.mha"], None),
        (["image10x10x10.mhd", "image10x10x10.zraw"], "generic-overlay"),
        (["image10x10x10.mhd", "image10x10x10.zraw"], None),
    ),
)
def test_upload_cases_to_archive(local_grand_challenge, files, interface):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    us = c.upload_cases(
        archive="archive",
        interface=interface,
        files=[Path(__file__).parent / "testdata" / f for f in files],
    )

    us = get_upload_session(c, us["pk"])

    # Check that only one image was created
    assert len(us["image_set"]) == 1

    image = get_image(c, us["image_set"][0])

    # And that it was added to the archive
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    archive_images = c.images.iterate_all(params={"archive": archive["pk"]})
    assert image["pk"] in [im["pk"] for im in archive_images]
    archive_items = c.archive_items.iterate_all(
        params={"archive": archive["pk"]}
    )
    # with the correct interface
    image_url_to_interface_slug_dict = {
        value["image"]: value["interface"]["slug"]
        for item in archive_items
        for value in item["values"]
        if value["image"]
    }
    if interface:
        assert image_url_to_interface_slug_dict[image["api_url"]] == interface
    else:
        assert (
            image_url_to_interface_slug_dict[image["api_url"]]
            == "generic-medical-image"
        )

    # And that we can download it
    response = c(url=image["files"][0]["file"], follow_redirects=True)
    assert response.status_code == 200


def test_upload_cases_to_archive_item_without_interface(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    item = next(c.archive_items.iterate_all(params={"archive": archive["pk"]}))

    # try upload without providing interface
    with pytest.raises(ValueError) as e:
        _ = c.upload_cases(
            archive_item=item["pk"],
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )
    assert "You need to define an interface for archive item uploads" in str(e)


def test_page_meta_info(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    archives = c.archives.page(limit=123)

    assert len(archives) == 1
    assert archives.offset == 0
    assert archives.limit == 123
    assert archives.total_count == 1


def test_upload_cases_to_archive_item_with_existing_interface(
    local_grand_challenge,
):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    item = next(c.archive_items.iterate_all(params={"archive": archive["pk"]}))

    us = c.upload_cases(
        archive_item=item["pk"],
        interface="generic-medical-image",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    us = get_upload_session(c, us["pk"])

    # Check that only one image was created
    assert len(us["image_set"]) == 1

    image = get_image(c, us["image_set"][0])

    # And that it was added to the archive item
    item = c.archive_items.detail(pk=item["pk"])
    assert image["api_url"] in [
        civ["image"] for civ in item["values"] if civ["image"]
    ]
    # with the correct interface
    im_to_interface = {
        civ["image"]: civ["interface"]["slug"] for civ in item["values"]
    }
    assert im_to_interface[image["api_url"]] == "generic-medical-image"


def test_upload_cases_to_archive_item_with_new_interface(
    local_grand_challenge,
):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    item = next(c.archive_items.iterate_all(params={"archive": archive["pk"]}))

    us = c.upload_cases(
        archive_item=item["pk"],
        interface="generic-overlay",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    us = get_upload_session(c, us["pk"])
    # Check that only one image was created
    assert len(us["image_set"]) == 1

    image = get_image(c, us["image_set"][0])

    # And that it was added to the archive item
    item = c.archive_items.detail(pk=item["pk"])
    assert image["api_url"] in [
        civ["image"] for civ in item["values"] if civ["image"]
    ]
    # with the correct interface
    im_to_interface = {
        civ["image"]: civ["interface"]["slug"] for civ in item["values"]
    }
    assert im_to_interface[image["api_url"]] == "generic-overlay"


@pytest.mark.parametrize("files", (["image10x10x101.mha"],))
def test_download_cases(local_grand_challenge, files, tmpdir):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    us = c.upload_cases(
        archive="archive",
        files=[Path(__file__).parent / "testdata" / f for f in files],
    )

    us = get_upload_session(c, us["pk"])

    # Check that we can download the uploaded image
    tmpdir = Path(tmpdir)

    @recurse_call
    def get_download():
        return c.images.download(
            filename=tmpdir / "image", url=us["image_set"][0]
        )

    downloaded_files = get_download()

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

    @recurse_call
    def run_job():
        return c.run_external_job(
            algorithm="test-algorithm-evaluation-1",
            inputs={
                "generic-medical-image": [
                    Path(__file__).parent / "testdata" / f for f in files
                ]
            },
        )

    # algorithm might not be ready yet
    job = run_job()

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
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    by_slug = c.reader_studies.detail(slug="reader-study")
    by_pk = c.reader_studies.detail(pk=by_slug["pk"])

    assert by_pk == by_slug


@pytest.mark.parametrize("key", ["slug", "pk"])
def test_detail_no_objects(local_grand_challenge, key):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
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


def test_add_and_update_file_to_archive_item(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    # check number of archive items
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    old_items_list = list(
        c.archive_items.iterate_all(params={"archive": archive["pk"]})
    )

    # create new archive item
    _ = c.upload_cases(
        archive="archive",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    # retrieve existing archive item pk
    items = get_archive_items(c, archive["pk"], len(old_items_list))

    old_civ_count = len(items[-1]["values"])

    with pytest.raises(ValueError) as e:
        _ = c.update_archive_item(
            archive_item_pk=items[-1]["pk"],
            values={
                "predictions-csv-file": [
                    Path(__file__).parent / "testdata" / f
                    for f in ["test.csv", "test.csv"]
                ]
            },
        )
    assert (
        "You can only upload one single file to a predictions-csv-file interface"
        in str(e)
    )

    _ = c.update_archive_item(
        archive_item_pk=items[-1]["pk"],
        values={
            "predictions-csv-file": [
                Path(__file__).parent / "testdata" / "test.csv"
            ]
        },
    )

    @recurse_call
    def get_updated_archive_item():
        archive_item = c.archive_items.detail(items[-1]["pk"])
        if len(archive_item["values"]) != old_civ_count + 1:
            # item has not been added
            raise ValueError
        return archive_item

    item_updated = get_updated_archive_item()

    csv_civ = item_updated["values"][-1]
    assert csv_civ["interface"]["slug"] == "predictions-csv-file"
    assert "test.csv" in csv_civ["file"]

    updated_civ_count = len(item_updated["values"])
    # a new pdf upload will overwrite the old pdf interface value
    _ = c.update_archive_item(
        archive_item_pk=items[-1]["pk"],
        values={
            "predictions-csv-file": [
                Path(__file__).parent / "testdata" / "test.csv"
            ]
        },
    )

    @recurse_call
    def get_updated_again_archive_item():
        archive_item = c.archive_items.detail(items[-1]["pk"])
        if csv_civ in archive_item["values"]:
            # item has not been added
            raise ValueError
        return archive_item

    item_updated_again = get_updated_again_archive_item()

    assert len(item_updated_again["values"]) == updated_civ_count
    new_csv_civ = item_updated_again["values"][-1]
    assert new_csv_civ["interface"]["slug"] == "predictions-csv-file"


def test_add_and_update_value_to_archive_item(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    # check number of archive items
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    old_items_list = list(
        c.archive_items.iterate_all(params={"archive": archive["pk"]})
    )

    # create new archive item
    _ = c.upload_cases(
        archive="archive",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    # retrieve existing archive item pk
    items = get_archive_items(c, archive["pk"], len(old_items_list))
    old_civ_count = len(items[-1]["values"])

    _ = c.update_archive_item(
        archive_item_pk=items[-1]["pk"],
        values={"results-json-file": {"foo": 0.5}},
    )

    @recurse_call
    def get_archive_item_detail():
        i = c.archive_items.detail(items[-1]["pk"])
        if len(i["values"]) != old_civ_count + 1:
            # item has been added
            raise ValueError
        return i

    item_updated = get_archive_item_detail()

    json_civ = item_updated["values"][-1]
    assert json_civ["interface"]["slug"] == "results-json-file"
    assert json_civ["value"] == {"foo": 0.5}
    updated_civ_count = len(item_updated["values"])

    _ = c.update_archive_item(
        archive_item_pk=items[-1]["pk"],
        values={"results-json-file": {"foo": 0.8}},
    )

    @recurse_call
    def get_updated_archive_item_detail():
        i = c.archive_items.detail(items[-1]["pk"])
        if json_civ in i["values"]:
            # item has not been added yet
            raise ValueError
        return i

    item_updated_again = get_updated_archive_item_detail()

    assert len(item_updated_again["values"]) == updated_civ_count
    new_json_civ = item_updated_again["values"][-1]
    assert new_json_civ["interface"]["slug"] == "results-json-file"
    assert new_json_civ["value"] == {"foo": 0.8}


def test_update_interface_kind_of_archive_item_image_civ(
    local_grand_challenge,
):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    # check number of archive items
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    old_items_list = list(
        c.archive_items.iterate_all(params={"archive": archive["pk"]})
    )

    # create new archive item
    _ = c.upload_cases(
        archive="archive",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    # retrieve existing archive item pk
    items = get_archive_items(c, archive["pk"], len(old_items_list))
    old_civ_count = len(items[-1]["values"])

    assert (
        items[-1]["values"][0]["interface"]["slug"] == "generic-medical-image"
    )
    im = items[-1]["values"][0]["image"]
    image = get_image(c, im)

    # change interface slug from generic-medical-image to generic-overlay
    _ = c.update_archive_item(
        archive_item_pk=items[-1]["pk"],
        values={"generic-overlay": image["api_url"]},
    )

    @recurse_call
    def get_updated_archive_items():
        i = c.archive_items.detail(items[-1]["pk"])
        if i["values"][-1]["interface"]["slug"] != "generic-overlay":
            # item has not been added yet
            raise ValueError
        return i

    item_updated = get_updated_archive_items()

    # still the same amount of civs
    assert len(item_updated["values"]) == old_civ_count
    assert "generic-medical-image" not in [
        value["interface"]["slug"] for value in item_updated["values"]
    ]
    assert item_updated["values"][-1]["image"] == im


def test_update_archive_item_with_non_existing_interface(
    local_grand_challenge,
):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    items = list(
        c.archive_items.iterate_all(params={"archive": archive["pk"]})
    )
    with pytest.raises(ValueError) as e:
        _ = c.update_archive_item(
            archive_item_pk=items[0]["pk"], values={"new-interface": 5}
        )
    assert "new-interface is not an existing interface" in str(e)


def test_update_archive_item_without_value(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    items = list(
        c.archive_items.iterate_all(params={"archive": archive["pk"]})
    )

    with pytest.raises(ValueError) as e:
        _ = c.update_archive_item(
            archive_item_pk=items[0]["pk"],
            values={"generic-medical-image": None},
        )
    assert "You need to provide a value for generic-medical-image" in str(e)


def test_create_display_sets_from_images(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    display_sets = [
        {
            "generic-medical-image": [
                Path(__file__).parent / "testdata" / "image10x10x101.mha"
            ]
        },
        {
            "generic-overlay": [
                Path(__file__).parent / "testdata" / "image10x10x101.mha"
            ]
        },
    ]

    created = c.create_display_sets_from_images(
        reader_study="reader-study", display_sets=display_sets
    )

    assert len(created) == 2

    reader_study = next(
        c.reader_studies.iterate_all(params={"slug": "reader-study"})
    )
    display_sets = list(
        c.reader_studies.display_sets.iterate_all(
            params={"reader_study": reader_study["pk"]}
        )
    )

    assert all([x in [y["pk"] for y in display_sets] for x in created])
