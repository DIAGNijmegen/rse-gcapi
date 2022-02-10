from io import BytesIO
from pathlib import Path
from time import sleep

import pytest
from httpx import HTTPStatusError

from gcapi import AsyncClient
from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound

RETINA_TOKEN = "f1f98a1733c05b12118785ffd995c250fe4d90da"
ADMIN_TOKEN = "1b9436200001f2eaf57cd77db075cbb60a49a00a"
READERSTUDY_TOKEN = "01614a77b1c0b4ecd402be50a8ff96188d5b011d"
DEMO_PARTICIPANT_TOKEN = "00aa710f4dc5621a0cb64b0795fbba02e39d7700"
ARCHIVE_TOKEN = "0d284528953157759d26c469297afcf6fd367f71"


@pytest.mark.parametrize(
    "annotation",
    [
        "retina_landmark_annotations",
        "retina_polygon_annotation_sets",
        "retina_single_polygon_annotations",
    ],
)
@pytest.mark.anyio
async def test_list_annotations(local_grand_challenge, annotation):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    ) as c:
        response = await getattr(c, annotation).list()
        assert len(response) == 0


@pytest.mark.anyio
async def test_create_landmark_annotation(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    ) as c:
        nil_uuid = "00000000-0000-4000-9000-000000000000"
        create_data = {
            "grader": 0,
            "singlelandmarkannotation_set": [
                {"image": nil_uuid, "landmarks": [[0, 0], [1, 1], [2, 2]]},
                {"image": nil_uuid, "landmarks": [[0, 0], [1, 1], [2, 2]]},
            ],
        }
        with pytest.raises(HTTPStatusError) as e:
            await c.retina_landmark_annotations.create(**create_data)
        response = e.value.response
        assert response.status_code == 400
        response = response.json()
        assert (
            response["grader"][0] == 'Invalid pk "0" - object does not exist.'
        )
        for sla_error in response["singlelandmarkannotation_set"]:
            assert (
                sla_error["image"][0]
                == f'Invalid pk "{nil_uuid}" - object does not exist.'
            )


@pytest.mark.anyio
async def test_create_polygon_annotation_set(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    ) as c:
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
            await c.retina_polygon_annotation_sets.create(**create_data)
        response = e.value.response
        assert response.status_code == 400
        response = response.json()
        assert (
            response["grader"][0] == 'Invalid pk "0" - object does not exist.'
        )
        assert (
            response["image"][0]
            == f'Invalid pk "{nil_uuid}" - object does not exist.'
        )
        assert response["name"][0] == "This field is required."


@pytest.mark.anyio
async def test_create_single_polygon_annotations(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    ) as c:
        create_data = {
            "z": 0,
            "value": [[0, 0], [1, 1], [2, 2]],
            "annotation_set": 0,
        }

        with pytest.raises(HTTPStatusError) as e:
            await c.retina_single_polygon_annotations.create(**create_data)
        response = e.value.response
        assert response.status_code == 400
        response = response.json()
        assert (
            response["annotation_set"][0]
            == 'Invalid pk "0" - object does not exist.'
        )


@pytest.mark.anyio
async def test_raw_image_and_upload_session(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    ) as c:
        assert await c.raw_image_upload_sessions.page() == []


@pytest.mark.anyio
async def test_local_response(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=RETINA_TOKEN
    ) as c:
        # Empty response, but it didn't error out so the server is responding
        assert await c.algorithms.page() == []


@pytest.mark.anyio
async def test_chunked_uploads(local_grand_challenge):
    file_to_upload = Path(__file__).parent / "testdata" / "rnddata"

    # admin
    async with AsyncClient(
        token=ADMIN_TOKEN, base_url=local_grand_challenge, verify=False
    ) as c_admin:
        existing_chunks_admin = (await c_admin(path="uploads/"))["count"]

        with open(file_to_upload, "rb") as f:
            await c_admin.uploads.upload_fileobj(
                fileobj=f, filename=file_to_upload.name
            )

        assert (await c_admin(path="uploads/"))[
            "count"
        ] == 1 + existing_chunks_admin

    # retina
    async with AsyncClient(
        token=RETINA_TOKEN, base_url=local_grand_challenge, verify=False
    ) as c_retina:
        existing_chunks_retina = (await c_retina(path="uploads/"))["count"]

        with open(file_to_upload, "rb") as f:
            await c_retina.uploads.upload_fileobj(
                fileobj=f, filename=file_to_upload.name
            )

        assert (await c_retina(path="uploads/"))[
            "count"
        ] == 1 + existing_chunks_retina

    async with AsyncClient(token="whatever") as c:
        with pytest.raises(HTTPStatusError):
            with open(file_to_upload, "rb") as f:
                await c.uploads.upload_fileobj(
                    fileobj=f, filename=file_to_upload.name
                )


@pytest.mark.parametrize(
    "files",
    (["image10x10x101.mha"], ["image10x10x10.mhd", "image10x10x10.zraw"]),
)
@pytest.mark.anyio
async def test_upload_cases_to_reader_study(local_grand_challenge, files):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        with pytest.raises(ValueError) as e:
            _ = await c.upload_cases(
                reader_study="reader-study",
                interface="generic-medical-image",
                files=[Path(__file__).parent / "testdata" / f for f in files],
            )
        assert (
            "An interface can only be defined for archive and archive item uploads"
            in str(e)
        )

        us = await c.upload_cases(
            reader_study="reader-study",
            files=[Path(__file__).parent / "testdata" / f for f in files],
        )

        for _ in range(60):
            us = await c.raw_image_upload_sessions.detail(us["pk"])
            if us["status"] == "Succeeded":
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        # Check that only one image was created
        assert len(us["image_set"]) == 1
        image = await c(url=us["image_set"][0])

        # And that it was added to the reader study
        rs = await (
            c.reader_studies.iterate_all(params={"slug": "reader-study"})
        ).__anext__()
        rs_images = c.images.iterate_all(params={"reader_study": rs["pk"]})
        assert image["pk"] in [im["pk"] async for im in rs_images]

        # And that we can download it
        response = await c(
            url=image["files"][0]["file"], follow_redirects=True
        )
        assert response.status_code == 200


@pytest.mark.parametrize(
    "files, interface",
    (
        (["image10x10x101.mha"], "generic-overlay"),
        (["image10x10x101.mha"], None),
        (["image10x10x10.mhd", "image10x10x10.zraw"], "generic-overlay"),
        (["image10x10x10.mhd", "image10x10x10.zraw"], None),
    ),
)
@pytest.mark.anyio
async def test_upload_cases_to_archive(
    local_grand_challenge, files, interface
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:

        us = await c.upload_cases(
            archive="archive",
            interface=interface,
            files=[Path(__file__).parent / "testdata" / f for f in files],
        )

        for _ in range(60):
            us = await c.raw_image_upload_sessions.detail(us["pk"])
            if us["status"] == "Succeeded":
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        # Check that only one image was created
        assert len(us["image_set"]) == 1
        for _ in range(60):
            try:
                image = await c(url=us["image_set"][0])
                break
            except HTTPStatusError:
                sleep(0.5)
        else:
            raise TimeoutError

        # And that it was added to the archive
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        archive_images = c.images.iterate_all(
            params={"archive": archive["id"]}
        )
        assert image["pk"] in [im["pk"] async for im in archive_images]
        archive_items = c.archive_items.iterate_all(
            params={"archive": archive["id"]}
        )

        # with the correct interface
        image_pk_to_interface_slug = {
            val["image"]["pk"]: val["interface"]["slug"]
            async for item in archive_items
            for val in item["values"]
            if val["image"]
        }

        if interface:
            assert image_pk_to_interface_slug[image["pk"]] == interface
        else:
            assert (
                image_pk_to_interface_slug[image["pk"]]
                == "generic-medical-image"
            )

        # And that we can download it
        response = await c(
            url=image["files"][0]["file"], follow_redirects=True
        )
        assert response.status_code == 200


@pytest.mark.anyio
async def test_upload_cases_to_archive_item_without_interface(
    local_grand_challenge,
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        # retrieve existing archive item pk
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        item = await (
            c.archive_items.iterate_all(params={"archive": archive["id"]})
        ).__anext__()

        with pytest.raises(ValueError) as e:
            _ = await c.upload_cases(
                archive_item=item["id"],
                files=[
                    Path(__file__).parent / "testdata" / "image10x10x101.mha"
                ],
            )
        assert (
            "You need to define an interface for archive item uploads"
            in str(e)
        )


@pytest.mark.anyio
async def test_upload_cases_to_archive_item_with_existing_interface(
    local_grand_challenge,
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        # retrieve existing archive item pk
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive["id"]})
        old_items_list = [item async for item in items]

        # create new archive item
        us = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )
        # retrieve existing archive item pk
        for _ in range(60):
            items = c.archive_items.iterate_all(
                params={"archive": archive["id"]}
            )
            items_list = [item async for item in items]
            if len(items_list) > len(old_items_list):
                # item has been added
                break
            else:
                sleep(0.5)

        us = await c.upload_cases(
            archive_item=items_list[-1]["id"],
            interface="generic-medical-image",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        for _ in range(60):
            us = await c.raw_image_upload_sessions.detail(us["pk"])
            if us["status"] == "Succeeded":
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        # Check that only one image was created
        assert len(us["image_set"]) == 1
        for _ in range(60):
            try:
                image = await c(url=us["image_set"][0])
                break
            except HTTPStatusError:
                sleep(0.5)
        else:
            raise TimeoutError

        # And that it was added to the archive item
        item = await c.archive_items.detail(pk=items_list[-1]["id"])
        assert image["pk"] in [civ["image"]["pk"] for civ in item["values"]]
        # with the correct interface
        im_to_interface = {
            civ["image"]["pk"]: civ["interface"]["slug"]
            for civ in item["values"]
        }
        assert im_to_interface[image["pk"]] == "generic-medical-image"


@pytest.mark.anyio
async def test_upload_cases_to_archive_item_with_new_interface(
    local_grand_challenge,
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive["id"]})
        old_items_list = [item async for item in items]

        # create new archive item
        us = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )
        # retrieve existing archive item pk
        for _ in range(60):
            items = c.archive_items.iterate_all(
                params={"archive": archive["id"]}
            )
            items_list = [item async for item in items]
            if len(items_list) > len(old_items_list):
                # item has been added
                break
            else:
                sleep(0.5)

        us = await c.upload_cases(
            archive_item=items_list[-1]["id"],
            interface="generic-overlay",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        for _ in range(60):
            us = await c.raw_image_upload_sessions.detail(us["pk"])
            if us["status"] == "Succeeded":
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        # Check that only one image was created
        assert len(us["image_set"]) == 1
        for _ in range(60):
            try:
                image = await c(url=us["image_set"][0])
                break
            except HTTPStatusError:
                sleep(0.5)
        else:
            raise TimeoutError

        # And that it was added to the archive item
        item = await c.archive_items.detail(pk=items_list[-1]["id"])
        assert image["pk"] in [civ["image"]["pk"] for civ in item["values"]]
        # with the correct interface
        im_to_interface = {
            civ["image"]["pk"]: civ["interface"]["slug"]
            for civ in item["values"]
        }
        assert im_to_interface[image["pk"]] == "generic-overlay"


@pytest.mark.parametrize("files", (["image10x10x101.mha"],))
@pytest.mark.anyio
async def test_download_cases(local_grand_challenge, files, tmpdir):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        us = await c.upload_cases(
            reader_study="reader-study",
            files=[Path(__file__).parent / "testdata" / f for f in files],
        )

        for _ in range(60):
            us = await c.raw_image_upload_sessions.detail(us["pk"])
            if us["status"] == "Succeeded":
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        # Check that we can download the uploaded image
        tmpdir = Path(tmpdir)
        downloaded_files = await c.images.download(
            filename=tmpdir / "image", url=us["image_set"][0]
        )
        assert len(downloaded_files) == 1

        # Check that the downloaded file is a mha file
        with downloaded_files[0].open("rb") as fp:
            line = fp.readline().decode("ascii").strip()
        assert line == "ObjectType = Image"


@pytest.mark.parametrize("files", (["image10x10x101.mha"],))
@pytest.mark.anyio
async def test_create_job_with_upload(local_grand_challenge, files):
    async with AsyncClient(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    ) as c:
        job = await c.run_external_job(
            algorithm="test-algorithm-evaluation-1",
            inputs={
                "generic-medical-image": [
                    Path(__file__).parent / "testdata" / f for f in files
                ]
            },
        )
        assert job["status"] == "Queued"
        assert len(job["inputs"]) == 1
        job = await c.algorithm_jobs.detail(job["pk"])
        assert job["status"] == "Queued"


@pytest.mark.anyio
async def test_get_algorithm_by_slug(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    ) as c:
        by_slug = await c.algorithms.detail(slug="test-algorithm-evaluation-1")
        by_pk = await c.algorithms.detail(pk=by_slug["pk"])

        assert by_pk == by_slug


@pytest.mark.anyio
async def test_get_reader_study_by_slug(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN,
    ) as c:
        by_slug = await c.reader_studies.detail(slug="reader-study")
        by_pk = await c.reader_studies.detail(pk=by_slug["pk"])

        assert by_pk == by_slug


@pytest.mark.parametrize("key", ["slug", "pk"])
@pytest.mark.anyio
async def test_detail_no_objects(local_grand_challenge, key):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN,
    ) as c:
        with pytest.raises(ObjectNotFound):
            await c.reader_studies.detail(**{key: "foo"})


@pytest.mark.anyio
async def test_detail_multiple_objects(local_grand_challenge):
    async with AsyncClient(
        token=ADMIN_TOKEN, base_url=local_grand_challenge, verify=False
    ) as c:
        await c.uploads.upload_fileobj(
            fileobj=BytesIO(b"123"), filename="test"
        )
        await c.uploads.upload_fileobj(
            fileobj=BytesIO(b"456"), filename="test"
        )

        with pytest.raises(MultipleObjectsReturned):
            await c.uploads.detail(slug="")


@pytest.mark.anyio
async def test_auth_headers_not_sent():
    async with AsyncClient(token="foo") as c:
        response = await c.uploads._put_chunk(
            chunk=BytesIO(b"123"), url="https://httpbin.org/put"
        )
        sent_headers = response.json()["headers"]
        assert not set(c._auth_header.keys()) & set(sent_headers.keys())


@pytest.mark.anyio
async def test_add_and_update_file_to_archive_item(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN,
    ) as c:
        # check number of archive items
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive["id"]})
        old_items_list = [item async for item in items]

        # create new archive item
        _ = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        # retrieve existing archive item pk
        for _ in range(60):
            items = c.archive_items.iterate_all(
                params={"archive": archive["id"]}
            )
            items_list = [item async for item in items]
            if len(items_list) > len(old_items_list):
                # item has been added
                break
            else:
                sleep(0.5)

        old_civ_count = len(items_list[-1]["values"])

        with pytest.raises(ValueError) as e:
            _ = await c.update_archive_item(
                archive_item_pk=items_list[-1]["id"],
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

        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1]["id"],
            values={
                "predictions-csv-file": [
                    Path(__file__).parent / "testdata" / "test.csv"
                ],
            },
        )

        for _ in range(60):
            item_updated = await c.archive_items.detail(items_list[-1]["id"])
            if len(item_updated["values"]) == old_civ_count + 1:
                # csv interface value has been added to item
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        csv_civ = item_updated["values"][-1]
        assert csv_civ["interface"]["slug"] == "predictions-csv-file"
        assert "test.csv" in csv_civ["file"]

        updated_civ_count = len(item_updated["values"])
        # a new pdf upload will overwrite the old pdf interface value
        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1]["id"],
            values={
                "predictions-csv-file": [
                    Path(__file__).parent / "testdata" / "test.csv"
                ],
            },
        )

        for _ in range(60):
            item_updated_again = await c.archive_items.detail(
                items_list[-1]["id"]
            )
            if csv_civ not in item_updated_again["values"]:
                # csv interface value has been added to item and the
                # previously added pdf civ is no longer attached to this archive item
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        assert len(item_updated_again["values"]) == updated_civ_count
        new_csv_civ = item_updated_again["values"][-1]
        assert new_csv_civ["interface"]["slug"] == "predictions-csv-file"


@pytest.mark.anyio
async def test_add_and_update_value_to_archive_item(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN,
    ) as c:
        # check number of archive items
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive["id"]})
        old_items_list = [item async for item in items]

        # create new archive item
        _ = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        # retrieve existing archive item pk
        for _ in range(60):
            items = c.archive_items.iterate_all(
                params={"archive": archive["id"]}
            )
            items_list = [item async for item in items]
            if len(items_list) > len(old_items_list):
                # item has been added
                break
            else:
                sleep(0.5)

        old_civ_count = len(items_list[-1]["values"])

        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1]["id"],
            values={"results-json-file": {"foo": 0.5}},
        )

        for _ in range(60):
            item_updated = await c.archive_items.detail(items_list[-1]["id"])
            if len(item_updated["values"]) == old_civ_count + 1:
                # results json interface value has been added to the item
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        json_civ = item_updated["values"][-1]
        assert json_civ["interface"]["slug"] == "results-json-file"
        assert json_civ["value"] == {"foo": 0.5}
        updated_civ_count = len(item_updated["values"])

        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1]["id"],
            values={"results-json-file": {"foo": 0.8}},
        )

        for _ in range(60):
            item_updated_again = await c.archive_items.detail(
                items_list[-1]["id"]
            )
            if json_civ not in item_updated_again["values"]:
                # results json interface value has been added to the item and
                # the previously added json civ is no longer attached
                # to this archive item
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        assert len(item_updated_again["values"]) == updated_civ_count
        new_json_civ = item_updated_again["values"][-1]
        assert new_json_civ["interface"]["slug"] == "results-json-file"
        assert new_json_civ["value"] == {"foo": 0.8}


@pytest.mark.anyio
async def test_update_interface_kind_of_archive_item_image_civ(
    local_grand_challenge,
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN,
    ) as c:
        # check number of archive items
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive["id"]})
        old_items_list = [item async for item in items]

        # create new archive item
        _ = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        # retrieve existing archive item pk
        for _ in range(60):
            items = c.archive_items.iterate_all(
                params={"archive": archive["id"]}
            )
            items_list = [item async for item in items]
            if len(items_list) > len(old_items_list):
                # item has been added
                break
            else:
                sleep(0.5)

        old_civ_count = len(items_list[-1]["values"])

        assert (
            items_list[-1]["values"][0]["interface"]["slug"]
            == "generic-medical-image"
        )
        im_pk = items_list[-1]["values"][0]["image"]["pk"]
        image = await c.images.detail(pk=im_pk)

        # change interface slug from generic-medical-image to generic-overlay
        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1]["id"],
            values={"generic-overlay": image["api_url"]},
        )

        for _ in range(60):
            item_updated = await c.archive_items.detail(items_list[-1]["id"])
            if (
                item_updated["values"][-1]["interface"]["slug"]
                == "generic-overlay"
            ):
                # interface type has been replaced
                break
            else:
                sleep(0.5)
        else:
            raise TimeoutError

        # still the same amount of civs
        assert len(item_updated["values"]) == old_civ_count
        assert "generic-medical-image" not in [
            value["interface"]["slug"] for value in item_updated["values"]
        ]
        assert item_updated["values"][-1]["image"]["pk"] == im_pk


@pytest.mark.anyio
async def test_update_archive_item_with_non_existing_interface(
    local_grand_challenge,
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN,
    ) as c:

        # retrieve existing archive item pk
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive["id"]})
        item_ids = [item["id"] async for item in items]
        with pytest.raises(ValueError) as e:
            _ = await c.update_archive_item(
                archive_item_pk=item_ids[0], values={"new-interface": 5},
            )
        assert "new-interface is not an existing interface" in str(e)


@pytest.mark.anyio
async def test_update_archive_item_without_value(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN,
    ) as c:

        # retrieve existing archive item pk
        archive = await (
            c.archives.iterate_all(params={"slug": "archive"})
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive["id"]})
        item_ids = [item["id"] async for item in items]

        with pytest.raises(ValueError) as e:
            _ = await c.update_archive_item(
                archive_item_pk=item_ids[0],
                values={"generic-medical-image": None},
            )
        assert "You need to provide a value for generic-medical-image" in str(
            e
        )
