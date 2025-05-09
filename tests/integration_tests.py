from functools import partial
from io import BytesIO
from pathlib import Path

import pytest
from httpx import HTTPStatusError

from gcapi import Client
from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound
from tests.utils import (
    ADMIN_TOKEN,
    ARCHIVE_TOKEN,
    DEMO_PARTICIPANT_TOKEN,
    READERSTUDY_TOKEN,
    recurse_call,
)


@recurse_call
def get_upload_session(client, upload_pk):
    upl = client.raw_image_upload_sessions.detail(upload_pk)
    if upl.status != "Succeeded":
        raise ValueError
    return upl


@recurse_call
def get_image(client, image_url):
    return client.images.detail(api_url=image_url)


@recurse_call
def get_archive_items(client, archive_pk, min_size):
    items = list(
        client.archive_items.iterate_all(params={"archive": archive_pk})
    )
    if len(items) <= min_size:
        raise ValueError
    return items


@recurse_call
def get_complete_civ_set(get_func, complete_num_civ):
    civ_set = get_func()
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
    assert len(c.raw_image_upload_sessions.page()) == 0


def test_local_response(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN)
    # Empty response, but it didn't error out so the server is responding
    assert len(c.algorithms.page()) == 0


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

    # archive
    c_archive = Client(
        token=ARCHIVE_TOKEN, base_url=local_grand_challenge, verify=False
    )
    existing_chunks_archive = c_archive(path="uploads/")["count"]

    with open(file_to_upload, "rb") as f:
        c_archive.uploads.upload_fileobj(
            fileobj=f, filename=file_to_upload.name
        )

    assert c_archive(path="uploads/")["count"] == 1 + existing_chunks_archive

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

    us = get_upload_session(c, us.pk)

    # Check that only one image was created
    assert len(us.image_set) == 1

    image = get_image(c, image_url=us.image_set[0])

    # And that it was added to the archive
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    archive_images = c.images.iterate_all(params={"archive": archive.pk})
    assert image.pk in [im.pk for im in archive_images]
    archive_items = c.archive_items.iterate_all(params={"archive": archive.pk})
    # with the correct interface
    image_url_to_interface_slug_dict = {
        value.image: value.interface.slug
        for item in archive_items
        for value in item.values
        if value.image
    }
    if interface:
        assert image_url_to_interface_slug_dict[image.api_url] == interface
    else:
        assert (
            image_url_to_interface_slug_dict[image.api_url]
            == "generic-medical-image"
        )

    # And that we can download it
    response = c(url=image.files[0].file, follow_redirects=True)
    assert response.status_code == 200


def test_upload_cases_to_archive_item_without_interface(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    item = next(c.archive_items.iterate_all(params={"archive": archive.pk}))

    # try upload without providing interface
    with pytest.raises(ValueError) as e:
        _ = c.upload_cases(
            archive_item=item.pk,
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
    item = next(c.archive_items.iterate_all(params={"archive": archive.pk}))

    us = c.upload_cases(
        archive_item=item.pk,
        interface="generic-medical-image",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    us = get_upload_session(c, us.pk)

    # Check that only one image was created
    assert len(us.image_set) == 1

    image = get_image(c, us.image_set[0])

    # And that it was added to the archive item
    item = c.archive_items.detail(pk=item.pk)
    assert image.api_url in [civ.image for civ in item.values if civ.image]
    # with the correct interface
    im_to_interface = {civ.image: civ.interface.slug for civ in item.values}
    assert im_to_interface[image.api_url] == "generic-medical-image"


def test_upload_cases_to_archive_item_with_new_interface(
    local_grand_challenge,
):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    item = next(c.archive_items.iterate_all(params={"archive": archive.pk}))

    us = c.upload_cases(
        archive_item=item.pk,
        interface="generic-overlay",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    us = get_upload_session(c, us.pk)
    # Check that only one image was created
    assert len(us.image_set) == 1

    image = get_image(c, us.image_set[0])

    # And that it was added to the archive item
    item = c.archive_items.detail(pk=item.pk)
    assert image.api_url in [civ.image for civ in item.values if civ.image]
    # with the correct interface
    im_to_interface = {civ.image: civ.interface.slug for civ in item.values}
    assert im_to_interface[image.api_url] == "generic-overlay"


@pytest.mark.parametrize("files", (["image10x10x101.mha"],))
def test_download_cases(local_grand_challenge, files, tmpdir):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    us = c.upload_cases(
        archive="archive",
        files=[Path(__file__).parent / "testdata" / f for f in files],
    )

    us = get_upload_session(c, us.pk)

    # Check that we can download the uploaded image
    tmpdir = Path(tmpdir)

    @recurse_call
    def get_download():
        return c.images.download(
            filename=tmpdir / "image", url=us.image_set[0]
        )

    downloaded_files = get_download()

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
        # (
        #    "test-algorithm-evaluation-file-0",
        #    "json-file",
        #    ["test.json"],
        # ),
    ),
)
def test_create_job_with_upload(
    local_grand_challenge, algorithm, interface, files
):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )

    @recurse_call
    def run_job():
        return c.run_external_job(
            algorithm=algorithm,
            inputs={
                interface: [
                    Path(__file__).parent / "testdata" / f for f in files
                ]
            },
        )

    # algorithm might not be ready yet
    job = run_job()

    assert job.status == "Validating inputs"
    job = c.algorithm_jobs.detail(job.pk)
    assert job.status in {"Validating inputs", "Queued", "Started"}


def test_get_algorithm_by_slug(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )

    by_slug = c.algorithms.detail(slug="test-algorithm-evaluation-image-0")
    by_pk = c.algorithms.detail(pk=by_slug.pk)
    by_api_url = c.algorithms.detail(by_api_url=by_slug.api_url)

    assert by_pk == by_slug == by_api_url


def test_get_reader_study_by_slug(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    by_slug = c.reader_studies.detail(slug="reader-study")
    by_pk = c.reader_studies.detail(pk=by_slug.pk)
    by_api_url = c.reader_studies.detail(by_api_url=by_slug.api_url)

    assert by_pk == by_slug == by_api_url


@pytest.mark.parametrize(
    "keys",
    [
        {"slug": "foo"},
        {"pk": "foo"},
        {"api_url": "foo"},
    ],
)
def test_detail_no_objects(local_grand_challenge, keys):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )
    if "api_url" in keys:
        keys = {
            "api_url": f"{local_grand_challenge}/reader-studies/{keys['api_url']}"
        }

    with pytest.raises(ObjectNotFound):
        c.reader_studies.detail(**keys)


@pytest.mark.parametrize(
    "keys",
    (
        ("api_url", "pk", "slug"),
        ("api_url", "pk"),
        ("api_url", "slug"),
        ("pk", "slug"),
    ),
)
def test_detail_multiple_args(local_grand_challenge, keys):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    with pytest.raises(ValueError):
        c.reader_studies.detail(**{k: "foo" for k in keys})


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
        c.archive_items.iterate_all(params={"archive": archive.pk})
    )

    # create new archive item
    _ = c.upload_cases(
        archive="archive",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    # retrieve existing archive item pk
    items = get_archive_items(c, archive.pk, len(old_items_list))

    old_items_pks = {item.pk for item in old_items_list}

    # get the new item
    target_archive_item = None
    for item in items:
        if item.pk not in old_items_pks:
            target_archive_item = item
            break

    # Sanity
    assert "predictions-csv-file" not in [
        item.interface.slug for item in target_archive_item.values
    ]

    with pytest.raises(ValueError) as e:
        _ = c.update_archive_item(
            archive_item_pk=target_archive_item.pk,
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
        archive_item_pk=target_archive_item.pk,
        values={
            "predictions-csv-file": [
                Path(__file__).parent / "testdata" / "test.csv"
            ]
        },
    )

    @recurse_call
    def get_updated_archive_item():
        archive_item = c.archive_items.detail(target_archive_item.pk)
        if len(archive_item.values) != len(target_archive_item.values) + 1:
            # item has not been added
            raise ValueError
        return archive_item

    updated_item = get_updated_archive_item()

    updated_civs_by_slug = {
        item.interface.slug: item for item in updated_item.values
    }

    assert (
        "predictions-csv-file" in updated_civs_by_slug
    ), "New civ did not get created"
    assert "test.csv" in updated_civs_by_slug["predictions-csv-file"].file

    # a new csv upload will overwrite the old csv interface value
    _ = c.update_archive_item(
        archive_item_pk=target_archive_item.pk,
        values={
            "predictions-csv-file": [
                Path(__file__).parent / "testdata" / "test2.csv"
            ]
        },
    )

    updated_again_civs_by_slug = {}

    @recurse_call
    def get_updated_again_archive_item():
        nonlocal updated_again_civs_by_slug
        archive_item = c.archive_items.detail(target_archive_item.pk)
        updated_again_civs_by_slug = {
            item.interface.slug: item for item in archive_item.values
        }
        if (
            "test2.csv"
            not in updated_again_civs_by_slug["predictions-csv-file"].file
        ):
            raise ValueError
        return archive_item

    get_updated_again_archive_item()

    assert {
        *updated_again_civs_by_slug.keys(),
    } == {
        *updated_civs_by_slug.keys(),
    }
    assert (
        "test2.csv" in updated_again_civs_by_slug["predictions-csv-file"].file
    )


def test_add_and_update_value_to_archive_item(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    # check number of archive items
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    old_items_list = list(
        c.archive_items.iterate_all(params={"archive": archive.pk})
    )

    # create new archive item
    _ = c.upload_cases(
        archive="archive",
        files=[Path(__file__).parent / "testdata" / "image10x10x101.mha"],
    )

    # retrieve existing archive item pk
    items = get_archive_items(c, archive.pk, len(old_items_list))
    old_civ_count = len(items[-1].values)

    _ = c.update_archive_item(
        archive_item_pk=items[-1].pk,
        values={"results-json-file": {"foo": 0.5}},
    )

    @recurse_call
    def get_archive_item_detail():
        i = c.archive_items.detail(items[-1].pk)
        if len(i.values) != old_civ_count + 1:
            # item has been added
            raise ValueError
        return i

    item_updated = get_archive_item_detail()

    json_civ = [
        civ
        for civ in item_updated.values
        if civ.interface.slug == "results-json-file"
    ][0]
    assert json_civ.value == {"foo": 0.5}
    updated_civ_count = len(item_updated.values)

    _ = c.update_archive_item(
        archive_item_pk=items[-1].pk,
        values={"results-json-file": {"foo": 0.8}},
    )

    @recurse_call
    def get_updated_archive_item_detail():
        i = c.archive_items.detail(items[-1].pk)
        if json_civ in i.values:
            # item has not been added yet
            raise ValueError
        return i

    item_updated_again = get_updated_archive_item_detail()

    assert len(item_updated_again.values) == updated_civ_count
    new_json_civ = [
        civ
        for civ in item_updated_again.values
        if civ.interface.slug == "results-json-file"
    ][0]
    assert new_json_civ.value == {"foo": 0.8}


def test_update_archive_item_with_non_existing_interface(
    local_grand_challenge,
):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    items = list(c.archive_items.iterate_all(params={"archive": archive.pk}))
    with pytest.raises(ValueError) as e:
        _ = c.update_archive_item(
            archive_item_pk=items[0].pk, values={"new-interface": 5}
        )
    assert "new-interface is not an existing interface" in str(e)


def test_update_archive_item_without_value(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    # retrieve existing archive item pk
    archive = next(c.archives.iterate_all(params={"slug": "archive"}))
    items = list(c.archive_items.iterate_all(params={"archive": archive.pk}))

    with pytest.raises(ValueError) as e:
        _ = c.update_archive_item(
            archive_item_pk=items[0].pk,
            values={"generic-medical-image": None},
        )
    assert "You need to provide a value for generic-medical-image" in str(e)


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
def test_add_cases_to_reader_study(display_sets, local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    added_display_sets = c.add_cases_to_reader_study(
        reader_study="reader-study", display_sets=display_sets
    )

    assert len(added_display_sets) == len(display_sets)

    reader_study = next(
        c.reader_studies.iterate_all(params={"slug": "reader-study"})
    )
    all_display_sets = list(
        c.reader_studies.display_sets.iterate_all(
            params={"reader_study": reader_study.pk}
        )
    )

    assert all(
        [x in [y.pk for y in all_display_sets] for x in added_display_sets]
    )

    @recurse_call
    def check_image(interface_value, expected_name):
        image = get_image(c, interface_value.image)
        assert image.name == expected_name

    def check_annotation(interface_value, expected):
        assert interface_value.value == expected

    @recurse_call
    def check_file(interface_value, expected_name):
        response = c(url=interface_value.file, follow_redirects=True)
        assert response.url.path.endswith(expected_name)

    for display_set_pk, display_set in zip(added_display_sets, display_sets):

        ds = get_complete_civ_set(
            get_func=partial(
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
                check_image(civ, file_name)
            elif civ.interface.kind == "2D bounding box":
                check_annotation(civ, value)
                pass
            elif civ.interface.super_kind == "File":
                file_name = value[0].name
                check_file(civ, file_name)


def test_add_cases_to_reader_study_invalid_interface(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    display_sets = [
        {
            "very-specific-medical-image": [
                Path(__file__).parent / "testdata" / "image10x10x101.mha"
            ]
        },
    ]

    with pytest.raises(ValueError) as e:
        c.add_cases_to_reader_study(
            reader_study="reader-study", display_sets=display_sets
        )

    assert str(e.value) == (
        "very-specific-medical-image is not an existing interface. "
        "Please provide one from this list: "
        "https://grand-challenge.org/components/interfaces/reader-studies/"
    )


def test_add_cases_to_reader_study_invalid_path(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    file_path = Path(__file__).parent / "testdata" / "image10x10x1011.mha"
    display_sets = [
        {"generic-medical-image": [file_path]},
    ]

    with pytest.raises(ValueError) as e:
        c.add_cases_to_reader_study(
            reader_study="reader-study", display_sets=display_sets
        )

    assert str(e.value) == (
        "Invalid file paths: " f"{{'generic-medical-image': ['{file_path}']}}"
    )


def test_add_cases_to_reader_study_invalid_value(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    display_sets = [
        {"generic-medical-image": "not a list"},
    ]

    with pytest.raises(ValueError) as e:
        c.add_cases_to_reader_study(
            reader_study="reader-study", display_sets=display_sets
        )

    assert str(e.value) == (
        "Values for generic-medical-image (image) should be a list of file paths."
    )


def test_add_cases_to_reader_study_multiple_files(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    files = [
        Path(__file__).parent / "testdata" / f
        for f in ["test.csv", "test.csv"]
    ]

    display_sets = [
        {"predictions-csv-file": files},
    ]

    with pytest.raises(ValueError) as e:
        c.add_cases_to_reader_study(
            reader_study="reader-study", display_sets=display_sets
        )

    assert str(e.value) == (
        "You can only upload one single file to interface "
        "predictions-csv-file (file)."
    )
