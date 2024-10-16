from io import BytesIO
from pathlib import Path

import pytest
from httpx import HTTPStatusError

from gcapi import AsyncClient
from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound
from tests.utils import (
    ADMIN_TOKEN,
    ARCHIVE_TOKEN,
    DEMO_PARTICIPANT_TOKEN,
    READERSTUDY_TOKEN,
    async_recurse_call,
)


@async_recurse_call
async def get_upload_session(client, upload_pk):
    upl = await client.raw_image_upload_sessions.detail(upload_pk)
    if upl.status != "Succeeded":
        raise ValueError
    return upl


@async_recurse_call
async def get_file(client, url):
    return await client(url=url, follow_redirects=True)


@async_recurse_call
async def get_archive_items(client, archive_pk, min_size):
    i = client.archive_items.iterate_all(params={"archive": archive_pk})
    il = [item async for item in i]
    if len(il) <= min_size:
        raise ValueError
    return il


@pytest.mark.anyio
async def test_raw_image_and_upload_session(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN
    ) as c:
        assert len(await c.raw_image_upload_sessions.page()) == 0


@pytest.mark.anyio
async def test_local_response(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN
    ) as c:
        # Empty response, but it didn't error out so the server is responding
        assert len(await c.algorithms.page()) == 0


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

    # archive
    async with AsyncClient(
        token=ARCHIVE_TOKEN, base_url=local_grand_challenge, verify=False
    ) as c_archive:
        existing_chunks_archive = (await c_archive(path="uploads/"))["count"]

        with open(file_to_upload, "rb") as f:
            await c_archive.uploads.upload_fileobj(
                fileobj=f, filename=file_to_upload.name
            )

        assert (await c_archive(path="uploads/"))[
            "count"
        ] == 1 + existing_chunks_archive

    async with AsyncClient(token="whatever") as c:
        with pytest.raises(HTTPStatusError):
            with open(file_to_upload, "rb") as f:
                await c.uploads.upload_fileobj(
                    fileobj=f, filename=file_to_upload.name
                )


@pytest.mark.anyio
async def test_page_meta_info(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        archives = await c.archives.page(limit=123)

        assert len(archives) == 1
        assert archives.offset == 0
        assert archives.limit == 123
        assert archives.total_count == 1


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

        us = await get_upload_session(c, us["pk"])

        # Check that only one image was created
        assert len(us.image_set) == 1
        image = await get_file(c, us.image_set[0])

        # And that it was added to the archive
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        archive_images = c.images.iterate_all(params={"archive": archive.pk})
        assert image["pk"] in [im.pk async for im in archive_images]
        archive_items = c.archive_items.iterate_all(
            params={"archive": archive.pk}
        )

        # with the correct interface
        image_url_to_interface_slug = {
            val.image: val.interface.slug
            async for item in archive_items
            for val in item.values
            if val.image
        }

        if interface:
            assert image_url_to_interface_slug[image["api_url"]] == interface
        else:
            assert (
                image_url_to_interface_slug[image["api_url"]]
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
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        item = await c.archive_items.iterate_all(
            params={"archive": archive.pk}
        ).__anext__()

        with pytest.raises(ValueError) as e:
            _ = await c.upload_cases(
                archive_item=item.pk,
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
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        old_items_list = [item async for item in items]

        # create new archive item
        us = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        # retrieve existing archive item pk
        items_list = await get_archive_items(
            c, archive.pk, len(old_items_list)
        )

        us = await c.upload_cases(
            archive_item=items_list[-1].pk,
            interface="generic-medical-image",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        us = await get_upload_session(c, us["pk"])

        # Check that only one image was created
        assert len(us.image_set) == 1
        image = await get_file(c, us.image_set[0])

        # And that it was added to the archive item
        item = await c.archive_items.detail(pk=items_list[-1].pk)
        assert image["api_url"] in [civ.image for civ in item.values]
        # with the correct interface
        im_to_interface = {
            civ.image: civ.interface.slug for civ in item.values
        }
        assert im_to_interface[image["api_url"]] == "generic-medical-image"


@pytest.mark.anyio
async def test_upload_cases_to_archive_item_with_new_interface(
    local_grand_challenge,
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        old_items_list = [item async for item in items]

        # create new archive item
        us = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        items_list = await get_archive_items(
            c, archive.pk, len(old_items_list)
        )

        us = await c.upload_cases(
            archive_item=items_list[-1].pk,
            interface="generic-overlay",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        us = await get_upload_session(c, us["pk"])

        # Check that only one image was created
        assert len(us.image_set) == 1
        image = await get_file(c, us.image_set[0])

        # And that it was added to the archive item
        item = await c.archive_items.detail(pk=items_list[-1].pk)
        assert image["api_url"] in [civ.image for civ in item.values]
        # with the correct interface
        im_to_interface = {
            civ.image: civ.interface.slug for civ in item.values
        }
        assert im_to_interface[image["api_url"]] == "generic-overlay"


@pytest.mark.parametrize("files", (["image10x10x101.mha"],))
@pytest.mark.anyio
async def test_download_cases(local_grand_challenge, files, tmpdir):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        us = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / f for f in files],
        )

        us = await get_upload_session(c, us["pk"])

        # Check that we can download the uploaded image
        tmpdir = Path(tmpdir)

        @async_recurse_call
        async def get_download():
            return await c.images.download(
                filename=tmpdir / "image", url=us.image_set[0]
            )

        downloaded_files = await get_download()

        assert len(downloaded_files) == 1

        # Check that the downloaded file is a mha file
        with downloaded_files[0].open("rb") as fp:
            line = fp.readline().decode("ascii").strip()
        assert line == "ObjectType = Image"


@pytest.mark.parametrize(
    "algorithm,interface,files",
    (
        (
            "test-algorithm-evaluation-image-0",
            "generic-medical-image",
            ["image10x10x101.mha"],
        ),
        # TODO this algorithm was removed from the test fixtures
        # ("test-algorithm-evaluation-file-0", "json-file", ["test.json"]),
    ),
)
@pytest.mark.anyio
async def test_create_job_with_upload(
    local_grand_challenge, algorithm, interface, files
):
    async with AsyncClient(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    ) as c:

        @async_recurse_call
        async def run_job():
            return await c.run_external_job(
                algorithm=algorithm,
                inputs={
                    interface: [
                        Path(__file__).parent / "testdata" / f for f in files
                    ]
                },
            )

        # algorithm might not be ready yet
        job = await run_job()

        assert job["status"] == "Validating inputs"
        assert len(job["inputs"]) == 1

        job = await c.algorithm_jobs.detail(job["pk"])
        assert job.status in {"Validating inputs", "Queued", "Started"}


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
@pytest.mark.anyio
async def test_input_types_upload_cases(local_grand_challenge, files):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        await c.upload_cases(archive="archive", files=files)


@pytest.mark.anyio
async def test_get_algorithm_by_slug(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    ) as c:
        by_slug = await c.algorithms.detail(
            slug="test-algorithm-evaluation-image-0"
        )
        by_pk = await c.algorithms.detail(pk=by_slug.pk)

        assert by_pk == by_slug


@pytest.mark.anyio
async def test_get_reader_study_by_slug(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        by_slug = await c.reader_studies.detail(slug="reader-study")
        by_pk = await c.reader_studies.detail(pk=by_slug.pk)

        assert by_pk == by_slug


@pytest.mark.parametrize("key", ["slug", "pk"])
@pytest.mark.anyio
async def test_detail_no_objects(local_grand_challenge, key):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
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
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        # check number of archive items
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        old_items_list = [item async for item in items]

        # create new archive item
        _ = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        # retrieve existing archive item pk
        items_list = await get_archive_items(
            c, archive.pk, len(old_items_list)
        )

        old_civ_count = len(items_list[-1].values)

        with pytest.raises(ValueError) as e:
            _ = await c.update_archive_item(
                archive_item_pk=items_list[-1].pk,
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
            archive_item_pk=items_list[-1].pk,
            values={
                "predictions-csv-file": [
                    Path(__file__).parent / "testdata" / "test.csv"
                ]
            },
        )

        @async_recurse_call
        async def get_archive_detail():
            item = await c.archive_items.detail(items_list[-1].pk)
            if len(item.values) != old_civ_count + 1:
                # csv interface value has not been added to item yet
                raise ValueError
            return item

        item_updated = await get_archive_detail()

        csv_civ = item_updated.values[-1]
        assert csv_civ.interface.slug == "predictions-csv-file"
        assert "test.csv" in csv_civ.file

        updated_civ_count = len(item_updated.values)
        # a new pdf upload will overwrite the old pdf interface value
        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1].pk,
            values={
                "predictions-csv-file": [
                    Path(__file__).parent / "testdata" / "test.csv"
                ]
            },
        )

        @async_recurse_call
        async def get_updated_again_archive_item():
            item = await c.archive_items.detail(items_list[-1].pk)
            if csv_civ in item.values:
                # csv interface value has been added to item
                raise ValueError
            return item

        item_updated_again = await get_updated_again_archive_item()

        assert len(item_updated_again.values) == updated_civ_count
        new_csv_civ = item_updated_again.values[-1]
        assert new_csv_civ.interface.slug == "predictions-csv-file"


@pytest.mark.anyio
async def test_add_and_update_value_to_archive_item(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        # check number of archive items
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        old_items_list = [item async for item in items]

        # create new archive item
        _ = await c.upload_cases(
            archive="archive",
            files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
        )

        # retrieve existing archive item pk
        items_list = await get_archive_items(
            c, archive.pk, len(old_items_list)
        )
        old_civ_count = len(items_list[-1].values)

        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1].pk,
            values={"results-json-file": {"foo": 0.5}},
        )

        @async_recurse_call
        async def get_archive_detail():
            item = await c.archive_items.detail(items_list[-1].pk)
            if len(item.values) != old_civ_count + 1:
                # csv interface value has been added to item
                raise ValueError
            return item

        item_updated = await get_archive_detail()

        json_civ = item_updated.values[-1]
        assert json_civ.interface.slug == "results-json-file"
        assert json_civ.value == {"foo": 0.5}
        updated_civ_count = len(item_updated.values)

        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1].pk,
            values={"results-json-file": {"foo": 0.8}},
        )

        @async_recurse_call
        async def get_updated_archive_detail():
            item = await c.archive_items.detail(items_list[-1].pk)
            if json_civ in item.values:
                # results json interface value has been added to the item and
                # the previously added json civ is no longer attached
                # to this archive item
                raise ValueError
            return item

        item_updated_again = await get_updated_archive_detail()

        assert len(item_updated_again.values) == updated_civ_count
        new_json_civ = item_updated_again.values[-1]
        assert new_json_civ.interface.slug == "results-json-file"
        assert new_json_civ.value == {"foo": 0.8}


@pytest.mark.anyio
async def test_update_archive_item_with_non_existing_interface(
    local_grand_challenge,
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        # retrieve existing archive item pk
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        item_ids = [item.pk async for item in items]
        with pytest.raises(ValueError) as e:
            _ = await c.update_archive_item(
                archive_item_pk=item_ids[0], values={"new-interface": 5}
            )
        assert "new-interface is not an existing interface" in str(e)


@pytest.mark.anyio
async def test_update_archive_item_without_value(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        # retrieve existing archive item pk
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        item_ids = [item.pk async for item in items]

        with pytest.raises(ValueError) as e:
            _ = await c.update_archive_item(
                archive_item_pk=item_ids[0],
                values={"generic-medical-image": None},
            )
        assert "You need to provide a value for generic-medical-image" in str(
            e
        )


@pytest.mark.parametrize(
    "display_sets",
    (
        [
            {
                "generic-medical-image": [
                    Path(__file__).parent / "testdata" / "image10x10x101.mha"
                ],
                "generic-overlay": [
                    Path(__file__).parent / "testdata" / "image10x10x10.mhd",
                    Path(__file__).parent / "testdata" / "image10x10x10.zraw",
                ],
                "annotation": {
                    "name": "forearm",
                    "type": "2D bounding box",
                    "corners": [
                        [20, 88, 0.5],
                        [83, 88, 0.5],
                        [83, 175, 0.5],
                        [20, 175, 0.5],
                    ],
                    "version": {"major": 1, "minor": 0},
                },
                "predictions-csv-file": [
                    Path(__file__).parent / "testdata" / "test.csv"
                ],
            },
            {
                "generic-medical-image": [
                    Path(__file__).parent / "testdata" / "image10x10x101.mha"
                ],
                "annotation": {
                    "name": "forearm",
                    "type": "2D bounding box",
                    "corners": [
                        [20, 88, 0.5],
                        [83, 88, 0.5],
                        [83, 175, 0.5],
                        [20, 175, 0.5],
                    ],
                    "version": {"major": 1, "minor": 0},
                },
            },
            {
                "annotation": {
                    "name": "forearm",
                    "type": "2D bounding box",
                    "corners": [
                        [20, 88, 0.5],
                        [83, 88, 0.5],
                        [83, 175, 0.5],
                        [20, 175, 0.5],
                    ],
                    "version": {"major": 1, "minor": 0},
                },
                "predictions-csv-file": [
                    Path(__file__).parent / "testdata" / "test.csv"
                ],
            },
            {
                "annotation": {
                    "name": "forearm",
                    "type": "2D bounding box",
                    "corners": [
                        [20, 88, 0.5],
                        [83, 88, 0.5],
                        [83, 175, 0.5],
                        [20, 175, 0.5],
                    ],
                    "version": {"major": 1, "minor": 0},
                },
            },
        ],
    ),
)
@pytest.mark.anyio
async def test_add_cases_to_reader_study(display_sets, local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        added_display_sets = await c.add_cases_to_reader_study(
            reader_study="reader-study", display_sets=display_sets
        )

        assert len(added_display_sets) == len(display_sets)

        reader_study = await c.reader_studies.iterate_all(
            params={"slug": "reader-study"}
        ).__anext__()
        all_display_sets = c.reader_studies.display_sets.iterate_all(
            params={"reader_study": reader_study.pk}
        )
        all_display_sets = {x.pk: x async for x in all_display_sets}
        assert all([x in all_display_sets for x in added_display_sets])

        @async_recurse_call
        async def check_image(interface_value, expected_name):
            image = await get_file(c, interface_value.image)
            assert image["name"] == expected_name

        def check_annotation(interface_value, expected):
            assert interface_value.value == expected

        @async_recurse_call
        async def check_file(interface_value, expected_name):
            response = await get_file(c, interface_value.file)
            assert response.url.path.endswith(expected_name)

        # Check for each display set that the values are added
        for display_set_pk, display_set in zip(
            added_display_sets, display_sets
        ):
            ds = await c.reader_studies.display_sets.detail(pk=display_set_pk)
            # may take a while for the images to be added
            while len(ds.values) != len(display_set):
                ds = await c.reader_studies.display_sets.detail(
                    pk=display_set_pk
                )

            for interface, value in display_set.items():
                civ = [
                    civ for civ in ds.values if civ.interface.slug == interface
                ][0]

                if civ.interface.super_kind == "Image":
                    file_name = value[0].name
                    await check_image(civ, file_name)
                elif civ.interface.kind == "2D bounding box":
                    check_annotation(civ, value)
                    pass
                elif civ.interface.super_kind == "File":
                    file_name = value[0].name
                    await check_file(civ, file_name)


@pytest.mark.anyio
async def test_add_cases_to_reader_study_invalid_interface(
    local_grand_challenge,
):
    display_sets = [
        {
            "very-specific-medical-image": [
                Path(__file__).parent / "testdata" / "image10x10x101.mha"
            ]
        }
    ]

    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        with pytest.raises(ValueError) as e:
            await c.add_cases_to_reader_study(
                reader_study="reader-study", display_sets=display_sets
            )

        assert str(e.value) == (
            "very-specific-medical-image is not an existing interface. "
            "Please provide one from this list: "
            "https://grand-challenge.org/components/interfaces/reader-studies/"
        )


@pytest.mark.anyio
async def test_add_cases_to_reader_study_invalid_path(
    local_grand_challenge,
):
    file_path = Path(__file__).parent / "testdata" / "image10x10x1011.mha"
    display_sets = [{"generic-medical-image": [file_path]}]

    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        with pytest.raises(ValueError) as e:
            await c.add_cases_to_reader_study(
                reader_study="reader-study", display_sets=display_sets
            )

        assert str(e.value) == (
            "Invalid file paths: "
            f"{{'generic-medical-image': ['{file_path}']}}"
        )


@pytest.mark.anyio
async def test_add_cases_to_reader_study_invalid_value(
    local_grand_challenge,
):
    display_sets = [{"generic-medical-image": "not a list"}]

    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        with pytest.raises(ValueError) as e:
            await c.add_cases_to_reader_study(
                reader_study="reader-study", display_sets=display_sets
            )

        assert str(e.value) == (
            "Values for generic-medical-image (image) should be a list of file paths."
        )


@pytest.mark.anyio
async def test_add_cases_to_reader_study_multiple_files(local_grand_challenge):
    files = [
        Path(__file__).parent / "testdata" / f
        for f in ["test.csv", "test.csv"]
    ]

    display_sets = [{"predictions-csv-file": files}]

    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        with pytest.raises(ValueError) as e:
            await c.add_cases_to_reader_study(
                reader_study="reader-study", display_sets=display_sets
            )

        assert str(e.value) == (
            "You can only upload one single file to interface "
            "predictions-csv-file (file)."
        )
