import json
from functools import partial
from io import BytesIO
from pathlib import Path

import pytest
from httpx import HTTPStatusError

from gcapi import AsyncClient
from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound
from tests.integration_tests import CIV_SET_PARAMS
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
async def get_display_items(client, reader_study_pk, min_size):
    i = client.reader_studies.display_sets.iterate_all(
        params={"reader-study": reader_study_pk}
    )
    il = [item async for item in i]
    if len(il) <= min_size:
        raise ValueError
    return il


@async_recurse_call
async def get_complete_civ_set(get_func, complete_num_civ):
    civ_set = await get_func()
    num_civ = len(civ_set.values)
    if num_civ != complete_num_civ:
        raise ValueError(
            f"Found {num_civ}, expected {complete_num_civ} values"
        )
    for civ in civ_set.values:
        if all(
            [
                civ.file is None,
                civ.image is None,
                civ.value is None,
            ]
        ):
            raise ValueError(f"Null values: {civ}")
    return civ_set


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
    file_to_upload = TESTDATA / "rnddata"

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
            files=[TESTDATA / f for f in files],
        )

        us = await get_upload_session(c, us.pk)

        # Check that only one image was created
        assert len(us.image_set) == 1
        image = await get_image(c, us.image_set[0])

        # And that it was added to the archive
        archive = await c.archives.detail(slug="archive")
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
        archive = await c.archives.detail(slug="archive")
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
        archive = await c.archives.detail(slug="archive")
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
        archive = await c.archives.detail(slug="archive")
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
            files=[TESTDATA / f for f in files],
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
            "test-algorithm-evaluation-image-1",
            "generic-medical-image",
            ["image10x10x101.mha"],
        ),
        # TODO this algorithm was removed from the test fixtures
        # ("test-algorithm-evaluation-file-1", "json-file", ["test.json"]),
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
                inputs={interface: [TESTDATA / f for f in files]},
            )

        # algorithm might not be ready yet
        job = await run_job()

        assert job.status == "Queued"
        assert len(job.inputs) == 1

        job = await c.algorithm_jobs.detail(job.pk)
        assert job.status in {"Queued", "Started"}


@pytest.mark.parametrize(
    "files",
    (
        # Path based
        [TESTDATA / "image10x10x101.mha"],
        # str based
        [str(TESTDATA / "image10x10x101.mha")],
        # mixed str and Path
        [
            str(TESTDATA / "image10x10x10.mhd"),
            TESTDATA / "image10x10x10.zraw",
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
            slug="test-algorithm-evaluation-image-1"
        )
        by_pk = await c.algorithms.detail(pk=by_slug.pk)
        by_api_url = await c.algorithms.detail(api_url=by_slug.api_url)

        assert by_pk == by_slug == by_api_url


@pytest.mark.anyio
async def test_get_reader_study_by_slug(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        by_slug = await c.reader_studies.detail(slug="reader-study")
        by_pk = await c.reader_studies.detail(pk=by_slug.pk)
        by_api_url = await c.reader_studies.detail(api_url=by_slug.api_url)

        assert by_pk == by_slug == by_api_url


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
        archive = await c.archives.detail(slug="archive")
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        old_items_list = [item async for item in items]

        # create new archive item
        _ = await c.upload_cases(
            archive="archive",
            files=[TESTDATA / "image10x10x101.mha"],
        )

        # retrieve existing archive item pk
        items_list = await get_archive_items(
            c, archive.pk, len(old_items_list)
        )

        old_civ_count = len(items_list[-1].values)

        _ = await c.update_archive_item(
            archive_item_pk=items_list[-1].pk,
            values={"predictions-csv-file": [TESTDATA / "test.csv"]},
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
            values={"predictions-csv-file": [TESTDATA / "test.csv"]},
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
        archive = await c.archives.detail(slug="archive")
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        old_items_list = [item async for item in items]

        # create new archive item
        _ = await c.upload_cases(
            archive="archive",
            files=[TESTDATA / "image10x10x101.mha"],
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

        json_civ = {v.interface.slug: v for v in item_updated.values}[
            "results-json-file"
        ]
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
        new_json_civ = {
            v.interface.slug: v for v in item_updated_again.values
        }["results-json-file"]
        assert new_json_civ.value == {"foo": 0.8}


@pytest.mark.anyio
async def test_add_and_update_value_to_display_set(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        # create new display set
        added_display_sets = await c.add_cases_to_reader_study(
            reader_study="reader-study",
            display_sets=[
                {"generic-medical-image": [TESTDATA / "image10x10x101.mha"]}
            ],
        )

        assert len(added_display_sets) == 1
        display_set_pk = added_display_sets[0]

        # Add a CIV (partially update)
        _ = await c.update_display_set(
            display_set_pk=display_set_pk,
            values={"results-json-file": {"foo": 0.5}},
        )

        @async_recurse_call
        async def get_display_set_detail(expected_num_values):
            item = await c.reader_studies.display_sets.detail(
                pk=display_set_pk
            )
            if len(item.values) != expected_num_values:
                # csv interface value has not yet been added to item
                raise ValueError
            return item

        item_updated = await get_display_set_detail(expected_num_values=2)

        json_civ = {v.interface.slug: v for v in item_updated.values}[
            "results-json-file"
        ]
        assert json_civ.value == {"foo": 0.5}

        # Overwrite a CIV (update)
        _ = await c.update_display_set(
            display_set_pk=display_set_pk,
            values={"results-json-file": {"foo": 0.8}},
        )

        @async_recurse_call
        async def get_updated_display_set_detail():
            item = await c.reader_studies.display_sets.detail(
                pk=display_set_pk
            )
            if json_civ in item.values:
                # results json interface value has been added to the item and
                # the previously added json civ is no longer attached
                # to this archive item
                raise ValueError
            return item

        item_updated_again = await get_updated_display_set_detail()

        assert len(item_updated_again.values) == 2

        new_json_civ = {
            v.interface.slug: v for v in item_updated_again.values
        }["results-json-file"]
        assert new_json_civ.value == {"foo": 0.8}


@pytest.mark.anyio
async def test_update_archive_item_with_non_existing_interface(
    local_grand_challenge,
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:
        # retrieve existing archive item pk
        archive = await c.archives.detail(slug="archive")
        items = c.archive_items.iterate_all(params={"archive": archive.pk})
        item_ids = [item.pk async for item in items]
        with pytest.raises(ValueError) as e:
            _ = await c.update_archive_item(
                archive_item_pk=item_ids[0], values={"new-interface": 5}
            )
        assert "new-interface is not an existing interface" in str(e)


@pytest.mark.parametrize(
    "display_sets",
    CIV_SET_PARAMS,
)
@pytest.mark.anyio
async def test_add_cases_to_reader_study(  # noqa: C901
    display_sets, local_grand_challenge
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:
        added_display_sets = await c.add_cases_to_reader_study(
            reader_study="reader-study", display_sets=display_sets
        )

        assert len(added_display_sets) == len(display_sets)

        reader_study = await c.reader_studies.detail(slug="reader-study")
        all_display_sets = c.reader_studies.display_sets.iterate_all(
            params={"reader_study": reader_study.pk}
        )
        all_display_sets = {x.pk: x async for x in all_display_sets}
        assert all([x in all_display_sets for x in added_display_sets])

        @async_recurse_call
        async def check_image(interface_value, expected_name):
            image = await get_image(c, interface_value.image)
            assert image.name == expected_name

        def check_annotation(interface_value, expected):
            assert interface_value.value == expected

        @async_recurse_call
        async def check_file(interface_value, expected_name):
            response = await c(url=interface_value.file, follow_redirects=True)
            assert response.url.path.endswith(expected_name)

        # Check for each display set that the values are added
        for display_set_pk, display_set in zip(
            added_display_sets, display_sets
        ):

            ds = await get_complete_civ_set(
                partial(
                    c.reader_studies.display_sets.detail, pk=display_set_pk
                ),
                complete_num_civ=len(display_set),
            )

            for interface, value in display_set.items():
                civ = [
                    civ for civ in ds.values if civ.interface.slug == interface
                ][0]

                if civ.interface.super_kind == "Image":
                    file_name = value[0].name
                    await check_image(civ, file_name)
                elif civ.interface.kind == "2D bounding box":
                    if isinstance(value, (str, Path)):
                        with open(value, "rb") as fd:
                            value = json.load(fd)
                    check_annotation(civ, value)
                elif civ.interface.super_kind == "File":
                    if isinstance(value, list):
                        value = value[0]
                    file_name = value.name
                    await check_file(civ, file_name)


@pytest.mark.parametrize(
    "archive_items",
    CIV_SET_PARAMS,
)
@pytest.mark.anyio
async def test_add_cases_to_archive(  # noqa: C901
    archive_items, local_grand_challenge
):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    ) as c:

        added_archive_items = await c.add_cases_to_archive(
            archive="archive", archive_items=archive_items
        )

        assert len(added_archive_items) == len(archive_items)

        archive = await c.archives.detail(slug="archive")

        all_archive_items = c.archive_items.iterate_all(
            params={"archive": archive.pk}
        )
        all_archive_items = {x.pk: x async for x in all_archive_items}

        assert all([x in all_archive_items for x in added_archive_items])

        @async_recurse_call
        async def check_image(interface_value, expected_name):
            image = await get_image(c, interface_value.image)
            assert image.name == expected_name

        def check_annotation(interface_value, expected):
            assert interface_value.value == expected

        @async_recurse_call
        async def check_file(interface_value, expected_name):
            response = await c(url=interface_value.file, follow_redirects=True)
            assert response.url.path.endswith(expected_name)

        for archive_item_pk, archive_item in zip(
            added_archive_items, archive_items
        ):

            ai = await get_complete_civ_set(
                partial(c.archive_items.detail, pk=archive_item_pk),
                complete_num_civ=len(archive_item),
            )

            for interface, value in archive_item.items():
                civ = [
                    civ for civ in ai.values if civ.interface.slug == interface
                ][0]

                if civ.interface.super_kind == "Image":
                    file_name = value[0].name
                    await check_image(civ, file_name)
                elif civ.interface.kind == "2D bounding box":
                    if isinstance(value, (str, Path)):
                        with open(value, "rb") as fd:
                            value = json.load(fd)
                    check_annotation(civ, value)
                    pass
                elif civ.interface.super_kind == "File":
                    if isinstance(value, list):
                        value = value[0]
                    file_name = value.name
                    await check_file(civ, file_name)


@pytest.mark.anyio
async def test_add_cases_to_reader_study_reuse_objects(local_grand_challenge):
    async with AsyncClient(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    ) as c:

        @async_recurse_call
        async def wait_for_import(pk):
            ds = await c.reader_studies.display_sets.detail(pk=pk)
            if len(ds.values) != 1:
                raise ValueError("No image imported yet")

        # Create an image / civ
        added_display_sets = await c.add_cases_to_reader_study(
            reader_study="reader-study",
            display_sets=[
                {
                    "generic-medical-image": [TESTDATA / "image10x10x101.mha"],
                }
            ],
        )

        assert len(added_display_sets) == 1
        display_set_pk = added_display_sets[0]

        await wait_for_import(display_set_pk)

        ds = await c.reader_studies.display_sets.detail(pk=display_set_pk)

        # Re-use both as a direct image and a CIV
        civ = ds.values[0]
        image = await c.images.detail(api_url=civ.image)

        added_display_sets = await c.add_cases_to_reader_study(
            reader_study="reader-study",
            display_sets=[
                {
                    "generic-medical-image": image,
                },
                {
                    "generic-medical-image": civ,
                },
            ],
        )
        assert len(added_display_sets) == 2
        for ds_pk in added_display_sets:
            ds = await c.reader_studies.display_sets.detail(pk=ds_pk)
            assert len(ds.values) == 1
