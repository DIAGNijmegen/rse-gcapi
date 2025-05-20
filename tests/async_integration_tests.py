from functools import partial
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

TESTDATA = Path(__file__).parent / "testdata"


@async_recurse_call
async def get_upload_session(client, upload_pk):
    upl = await client.raw_image_upload_sessions.detail(upload_pk)
    if upl.status != "Succeeded":
        raise ValueError
    return upl


@async_recurse_call
async def get_image(client, url):
    return await client.images.detail(api_url=url)


@async_recurse_call
async def get_archive_items(client, archive_pk, min_size):
    i = client.archive_items.iterate_all(params={"archive": archive_pk})
    il = [item async for item in i]
    if len(il) <= min_size:
        raise ValueError
    return il


@async_recurse_call
async def get_complete_socket_value_set(get_func, complete_num_sv):
    sv_set = await get_func()
    num_sv = len(sv_set.values)
    if num_sv != complete_num_sv:
        raise ValueError(f"Found {num_sv}, expected {complete_num_sv} values")
    for sv in sv_set.values:
        if all(
            [
                sv.file is None,
                sv.image is None,
                sv.value is None,
            ]
        ):
            raise ValueError(f"Null values: {sv}")
    return sv_set


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

        us = await get_upload_session(c, us.pk)

        # Check that only one image was created
        assert len(us.image_set) == 1
        image = await get_image(c, us.image_set[0])

        # And that it was added to the archive
        archive = await c.archives.iterate_all(
            params={"slug": "archive"}
        ).__anext__()
        archive_images = c.images.iterate_all(params={"archive": archive.pk})
        assert image.pk in [im.pk async for im in archive_images]
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
            assert image_url_to_interface_slug[image.api_url] == interface
        else:
            assert (
                image_url_to_interface_slug[image.api_url]
                == "generic-medical-image"
            )

        # And that we can download it
        response = await c(url=image.files[0].file, follow_redirects=True)
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
                files=[TESTDATA / "image10x10x101.mha"],
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
            files=[TESTDATA / "image10x10x101.mha"],
        )

        # retrieve existing archive item pk
        items_list = await get_archive_items(
            c, archive.pk, len(old_items_list)
        )

        us = await c.upload_cases(
            archive_item=items_list[-1].pk,
            interface="generic-medical-image",
            files=[TESTDATA / "image10x10x101.mha"],
        )

        us = await get_upload_session(c, us.pk)

        # Check that only one image was created
        assert len(us.image_set) == 1
        image = await get_image(c, us.image_set[0])

        # And that it was added to the archive item
        item = await c.archive_items.detail(pk=items_list[-1].pk)
        assert image.api_url in [civ.image for civ in item.values]
        # with the correct interface
        im_to_interface = {
            civ.image: civ.interface.slug for civ in item.values
        }
        assert im_to_interface[image.api_url] == "generic-medical-image"


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
            files=[TESTDATA / "image10x10x101.mha"],
        )

        items_list = await get_archive_items(
            c, archive.pk, len(old_items_list)
        )

        us = await c.upload_cases(
            archive_item=items_list[-1].pk,
            interface="generic-overlay",
            files=[TESTDATA / "image10x10x101.mha"],
        )

        us = await get_upload_session(c, us.pk)

        # Check that only one image was created
        assert len(us.image_set) == 1
        image = await get_image(c, us.image_set[0])

        # And that it was added to the archive item
        item = await c.archive_items.detail(pk=items_list[-1].pk)
        assert image.api_url in [civ.image for civ in item.values]
        # with the correct interface
        im_to_interface = {
            civ.image: civ.interface.slug for civ in item.values
        }
        assert im_to_interface[image.api_url] == "generic-overlay"


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

        us = await get_upload_session(c, us.pk)

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

        assert job.status == "Validating inputs"

        @async_recurse_call
        async def check_job_status():
            j = await c.algorithm_jobs.detail(job.pk)
            if j.status in {
                "Queued",
                "Started",
                "Re-Queued",
                "Provisioning",
                "Provisioned",
                "Executing",
                "Executed",
                "Parsing Outputs",
                "Executing Algorithm",
                "Validating inputs",
            }:
                raise ValueError(f"Job not in incorrect state ({j.status})")

        await check_job_status()


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
async def test_auth_headers_not_sent(local_httpbin):
    async with AsyncClient(token="foo") as c:
        response = await c.uploads._put_chunk(
            chunk=BytesIO(b"123"), url=f"{local_httpbin}put"
        )
        sent_headers = response.json()["headers"]
        assert not set(c._auth_header.keys()) & set(sent_headers.keys())


@pytest.mark.anyio
async def test_add_and_update_file_to_archive_item(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        # create new archive item
        archive_item_pks = await c.add_cases_to_archive(
            archive="archive",
            archive_items=[
                {"generic-medical-image": TESTDATA / "image10x10x101.mha"},
            ],
        )

        @async_recurse_call
        async def get_target_archive_item():
            # Wait for the image to be added (async task)
            archive_item = await c.archive_items.detail(pk=archive_item_pks[0])
            if len(archive_item.values) != 1:
                # item has not been added
                raise ValueError
            return archive_item

        target_archive_item = await get_target_archive_item()

        # Update it again, with a CSV this time
        _ = await c.update_archive_item(
            archive_item_pk=target_archive_item.pk,
            values={
                "predictions-csv-file": [TESTDATA / "test.csv"],
            },
        )

        @async_recurse_call
        async def get_updated_archive_item():
            archive_item = await c.archive_items.detail(target_archive_item.pk)
            if len(archive_item.values) != 2:
                # item has not been added
                raise ValueError
            return archive_item

        item_updated = await get_updated_archive_item()

        csv_socket_value = next(
            v
            for v in item_updated.values
            if v.interface.slug == "predictions-csv-file"
        )
        assert "test.csv" in csv_socket_value.file

        updated_socket_value_count = len(item_updated.values)

        # Yet again, update a new CSV that should replace the old one
        await c.update_archive_item(
            archive_item_pk=target_archive_item.pk,
            values={
                "predictions-csv-file": [TESTDATA / "test2.csv"],
            },
        )

        @async_recurse_call
        async def get_updated_again_archive_item():
            archive_item = await c.archive_items.detail(target_archive_item.pk)
            if csv_socket_value.pk in [v.pk for v in archive_item.values]:
                # old value still there
                raise ValueError
            return archive_item

        item_updated_again = await get_updated_again_archive_item()

        assert len(item_updated_again.values) == updated_socket_value_count
        new_csv_socket_value = next(
            v
            for v in item_updated_again.values
            if v.interface.slug == "predictions-csv-file"
        )
        assert "test2.csv" in new_csv_socket_value.file


@pytest.mark.anyio
async def test_add_and_update_file_to_display_set(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        # Create new display set
        display_set_pks = await c.add_cases_to_reader_study(
            reader_study="reader-study",
            display_sets=[
                {"generic-medical-image": TESTDATA / "image10x10x101.mha"},
            ],
        )

        @async_recurse_call
        async def get_target_display_set():
            display_set = await c.reader_studies.display_sets.detail(
                pk=display_set_pks[0]
            )
            if len(display_set.values) != 1:
                raise ValueError
            return display_set

        target_display_set = await get_target_display_set()

        # Update with a CSV file
        await c.update_display_set(
            display_set_pk=target_display_set.pk,
            values={
                "predictions-csv-file": [TESTDATA / "test.csv"],
            },
        )

        @async_recurse_call
        async def get_updated_display_set():
            display_set = await c.reader_studies.display_sets.detail(
                target_display_set.pk
            )
            if len(display_set.values) != 2:
                raise ValueError
            return display_set

        item_updated = await get_updated_display_set()

        csv_socket_value = next(
            v
            for v in item_updated.values
            if v.interface.slug == "predictions-csv-file"
        )
        assert "test.csv" in csv_socket_value.file

        updated_socket_value_count = len(item_updated.values)

        # Replace the CSV with a new one
        await c.update_display_set(
            display_set_pk=target_display_set.pk,
            values={
                "predictions-csv-file": [TESTDATA / "test2.csv"],
            },
        )

        @async_recurse_call
        async def get_updated_again_display_set():
            display_set = await c.reader_studies.display_sets.detail(
                target_display_set.pk
            )
            if csv_socket_value.pk in [v.pk for v in display_set.values]:
                raise ValueError
            return display_set

        item_updated_again = await get_updated_again_display_set()

        assert len(item_updated_again.values) == updated_socket_value_count
        new_csv_socket_value = next(
            v
            for v in item_updated_again.values
            if v.interface.slug == "predictions-csv-file"
        )
        assert "test2.csv" in new_csv_socket_value.file


@pytest.mark.anyio
async def test_add_and_update_value_to_archive_item(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:

        # create new archive item
        archive_item_pks = await c.add_cases_to_archive(
            archive="archive",
            archive_items=[
                {
                    "metrics-json-file": {"foo": "bar"},
                },
            ],
        )

        archive_item = await c.archive_items.detail(pk=archive_item_pks[0])

        assert archive_item.values[0].interface.slug == "metrics-json-file"
        assert archive_item.values[0].value["foo"] == "bar"

        # Update value
        archive_item = await c.update_archive_item(
            archive_item_pk=archive_item.pk,
            values={
                "metrics-json-file": {"foo2": "bar2"},
            },
        )

        assert (
            archive_item.values[0].value["foo2"] == "bar2"
        ), "Sanity, values are applied directly"

        updated_archive_item = await c.archive_items.detail(
            pk=archive_item_pks[0]
        )
        assert (
            updated_archive_item.values[0].interface.slug
            == "metrics-json-file"
        )
        assert updated_archive_item.values[0].value["foo2"] == "bar2"


@pytest.mark.anyio
async def test_add_and_update_value_to_display_set(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:

        # Create new display set with a structured value
        display_set_pks = await c.add_cases_to_reader_study(
            reader_study="reader-study",
            display_sets=[
                {
                    "metrics-json-file": {"foo": "bar"},
                },
            ],
        )

        display_set = await c.reader_studies.display_sets.detail(
            pk=display_set_pks[0]
        )

        assert display_set.values[0].interface.slug == "metrics-json-file"
        assert display_set.values[0].value["foo"] == "bar"

        # Update the structured value
        display_set = await c.update_display_set(
            display_set_pk=display_set.pk,
            values={
                "metrics-json-file": {"foo2": "bar2"},
            },
        )

        assert (
            display_set.values[0].value["foo2"] == "bar2"
        ), "Sanity, values are applied directly"

        updated_display_set = await c.reader_studies.display_sets.detail(
            pk=display_set_pks[0]
        )
        assert (
            updated_display_set.values[0].interface.slug == "metrics-json-file"
        )
        assert updated_display_set.values[0].value["foo2"] == "bar2"


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
        async def check_image(socket_value, expected_name):
            image = await get_image(c, socket_value.image)
            assert image.name == expected_name

        def check_annotation(socket_value, expected):
            assert socket_value.value == expected

        @async_recurse_call
        async def check_file(socket_value, expected_name):
            response = await c(url=socket_value.file, follow_redirects=True)
            assert response.url.path.endswith(expected_name)

        # Check for each display set that the values are added
        for display_set_pk, display_set in zip(
            added_display_sets, display_sets
        ):

            ds = await get_complete_socket_value_set(
                partial(
                    c.reader_studies.display_sets.detail, pk=display_set_pk
                ),
                complete_num_sv=len(display_set),
            )

            for socket_slug, value in display_set.items():
                sv = [
                    sv for sv in ds.values if sv.interface.slug == socket_slug
                ][0]

                if sv.interface.super_kind == "Image":
                    file_name = value[0].name
                    await check_image(sv, file_name)
                elif sv.interface.kind == "2D bounding box":
                    check_annotation(sv, value)
                    pass
                elif sv.interface.super_kind == "File":
                    file_name = value[0].name
                    await check_file(sv, file_name)


@pytest.mark.anyio
async def test_add_cases_to_reader_study_invalid_socket(
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
async def test_add_cases_to_archive_invalid_socket(local_grand_challenge):

    archive_items = [
        {
            "very-specific-medical-image": [
                Path(__file__).parent / "testdata" / "image10x10x101.mha"
            ]
        },
    ]

    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:

        with pytest.raises(ValueError) as e:
            await c.add_cases_to_archive(
                archive="archive", archive_items=archive_items
            )

        assert str(e.value) == (
            "very-specific-medical-image is not an existing interface. "
            "Please provide one from this list: "
            "https://grand-challenge.org/components/interfaces/inputs/"
        )
