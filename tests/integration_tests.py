from functools import partial
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from httpx import HTTPStatusError

import gcapi
from gcapi import Client
from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound
from tests.utils import (
    ADMIN_TOKEN,
    ARCHIVE_TOKEN,
    DEMO_PARTICIPANT_TOKEN,
    READERSTUDY_TOKEN,
    recurse_call,
)

TESTDATA = Path(__file__).parent / "testdata"


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
def get_complete_socket_value_set(get_func, complete_num_sv):
    sv_set = get_func()
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


def test_raw_image_and_upload_session(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN)
    assert len(c.raw_image_upload_sessions.page()) == 0


def test_local_response(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN)
    # Empty response, but it didn't error out so the server is responding
    assert len(c.algorithms.page()) == 0


def test_get_display_sets(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )
    display_sets = list(
        c.reader_studies.display_sets.iterate_all(
            params={"slug": "reader-study"}
        )
    )
    assert len(display_sets) > 0
    assert isinstance(display_sets[0], gcapi.models.DisplaySet)


def test_get_algorithm_images(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )
    algorithm = c.algorithms.detail(slug="test-algorithm-evaluation-image-0")
    algorithm_images = list(
        c.algorithm_images.iterate_all(params={"algorithm": algorithm.pk})
    )
    assert len(algorithm_images) > 0
    assert isinstance(algorithm_images[0], gcapi.models.AlgorithmImage)


def test_get_answers(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )
    answers = list(
        c.reader_studies.answers.iterate_all(params={"slug": "reader-study"})
    )
    assert len(answers) > 0
    assert isinstance(answers[0], gcapi.models.Answer)


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


def test_page_meta_info(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    archives = c.archives.page(limit=123)

    assert len(archives) == 1
    assert archives.offset == 0
    assert archives.limit == 123
    assert archives.total_count == 1


@pytest.mark.parametrize("files", (["image10x10x101.mha"],))
def test_download_cases(local_grand_challenge, files, tmpdir):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    created_archive_items = c.add_cases_to_archive(
        archive="archive",
        archive_items=[
            {
                "generic-medical-image": [
                    Path(__file__).parent / "testdata" / f for f in files
                ]
            }
        ],
    )

    # Wait for upload to complete
    get_complete_socket_value_set(
        get_func=lambda: c.archive_items.detail(created_archive_items[0]),
        complete_num_sv=1,
    )

    archive_item = c.archive_items.detail(created_archive_items[0])

    # Check that we can download the uploaded image
    tmpdir = Path(tmpdir)

    downloaded_files = c.images.download(
        filename=tmpdir / "image", url=archive_item.values[0].image
    )

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

    @recurse_call
    async def check_job_status():
        j = c.algorithm_jobs.detail(job.pk)
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

    check_job_status()


def test_get_algorithm_by_slug(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )

    by_slug = c.algorithms.detail(slug="test-algorithm-evaluation-image-0")
    by_pk = c.algorithms.detail(pk=by_slug.pk)
    by_api_url = c.algorithms.detail(by_api_url=by_slug.api_url)

    assert by_pk.pk == by_slug.pk == by_api_url.pk


def test_get_reader_study_by_slug(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    by_slug = c.reader_studies.detail(slug="reader-study")
    by_pk = c.reader_studies.detail(pk=by_slug.pk)
    by_api_url = c.reader_studies.detail(by_api_url=by_slug.api_url)

    assert by_pk.pk == by_slug.pk == by_api_url.pk


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


def test_auth_headers_not_sent(local_httpbin):
    c = Client(token="foo")
    response = c.uploads._put_chunk(
        chunk=BytesIO(b"123"), url=f"{local_httpbin}put"
    )
    sent_headers = response.json()["headers"]
    assert not set(c._auth_header.keys()) & set(sent_headers.keys())


def test_add_and_update_file_to_archive_item(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    # create new archive item
    archive_item_pks = c.add_cases_to_archive(
        archive="archive",
        archive_items=[
            {"generic-medical-image": TESTDATA / "image10x10x101.mha"},
        ],
    )

    @recurse_call
    def get_target_archive_item():
        # Wait for the image to be added (async task)
        archive_item = c.archive_items.detail(pk=archive_item_pks[0])
        if len(archive_item.values) != 1:
            # item has not been added
            raise ValueError
        return archive_item

    target_archive_item = get_target_archive_item()

    # Update it again, with a CSV this time
    _ = c.update_archive_item(
        archive_item_pk=target_archive_item.pk,
        values={
            "predictions-csv-file": [TESTDATA / "test.csv"],
        },
    )

    @recurse_call
    def get_updated_archive_item():
        archive_item = c.archive_items.detail(target_archive_item.pk)
        if len(archive_item.values) != 2:
            # item has not been added
            raise ValueError
        return archive_item

    item_updated = get_updated_archive_item()

    csv_socket_value = next(
        v
        for v in item_updated.values
        if v.interface.slug == "predictions-csv-file"
    )
    assert "test.csv" in csv_socket_value.file

    updated_socket_value_count = len(item_updated.values)

    # Yet again, update a new CSV that should replace the old one
    c.update_archive_item(
        archive_item_pk=target_archive_item.pk,
        values={
            "predictions-csv-file": [TESTDATA / "test2.csv"],
        },
    )

    @recurse_call
    def get_updated_again_archive_item():
        archive_item = c.archive_items.detail(target_archive_item.pk)
        if csv_socket_value.pk in [v.pk for v in archive_item.values]:
            # old value still there
            raise ValueError
        return archive_item

    item_updated_again = get_updated_again_archive_item()

    assert len(item_updated_again.values) == updated_socket_value_count
    new_csv_socket_value = next(
        v
        for v in item_updated_again.values
        if v.interface.slug == "predictions-csv-file"
    )
    assert new_csv_socket_value.interface.slug == "predictions-csv-file"
    assert "test2.csv" in new_csv_socket_value.file


def test_add_and_update_file_to_display_set(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    # Create a new display set in the reader study
    display_set_pks = c.add_cases_to_reader_study(
        reader_study="reader-study",
        display_sets=[
            {"generic-medical-image": TESTDATA / "image10x10x101.mha"},
        ],
    )

    @recurse_call
    def get_target_display_set():
        # Wait for the image to be added (async task)
        display_set = c.reader_studies.display_sets.detail(
            pk=display_set_pks[0]
        )
        if len(display_set.values) != 1:
            raise ValueError
        return display_set

    target_display_set = get_target_display_set()

    # Update the display set with a CSV file
    _ = c.update_display_set(
        display_set_pk=target_display_set.pk,
        values={
            "predictions-csv-file": [TESTDATA / "test.csv"],
        },
    )

    @recurse_call
    def get_updated_display_set():
        display_set = c.reader_studies.display_sets.detail(
            target_display_set.pk
        )
        if len(display_set.values) != 2:
            raise ValueError
        return display_set

    item_updated = get_updated_display_set()

    csv_socket_value = next(
        v
        for v in item_updated.values
        if v.interface.slug == "predictions-csv-file"
    )
    assert "test.csv" in csv_socket_value.file

    updated_socket_value_count = len(item_updated.values)

    # Update again, replacing the previous CSV with a new one
    c.update_display_set(
        display_set_pk=target_display_set.pk,
        values={
            "predictions-csv-file": [TESTDATA / "test2.csv"],
        },
    )

    @recurse_call
    def get_updated_again_display_set():
        display_set = c.reader_studies.display_sets.detail(
            target_display_set.pk
        )
        if csv_socket_value.pk in [v.pk for v in display_set.values]:
            raise ValueError
        return display_set

    item_updated_again = get_updated_again_display_set()

    assert len(item_updated_again.values) == updated_socket_value_count
    new_csv_socket_value = next(
        v
        for v in item_updated_again.values
        if v.interface.slug == "predictions-csv-file"
    )
    assert new_csv_socket_value.interface.slug == "predictions-csv-file"
    assert "test2.csv" in new_csv_socket_value.file


def test_add_and_update_value_to_archive_item(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    # create new archive item
    archive_item_pks = c.add_cases_to_archive(
        archive="archive",
        archive_items=[
            {
                "metrics-json-file": {"foo": "bar"},
            },
        ],
    )

    archive_item = c.archive_items.detail(pk=archive_item_pks[0])

    assert archive_item.values[0].interface.slug == "metrics-json-file"
    value = cast(dict, archive_item.values[0].value)
    assert value["foo"] == "bar"

    # Update value
    updated_archive_item = c.update_archive_item(
        archive_item_pk=archive_item.pk,
        values={
            "metrics-json-file": {"foo2": "bar2"},
        },
    )

    value = cast(dict, cast(list, updated_archive_item.values)[0].value)
    assert value["foo2"] == "bar2", "Sanity, values are applied directly"

    archive_item = c.archive_items.detail(pk=archive_item_pks[0])
    assert archive_item.values[0].interface.slug == "metrics-json-file"
    value = cast(dict, archive_item.values[0].value)
    assert value["foo2"] == "bar2"


def test_add_and_update_value_to_display_set(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    # Create new display set with a structured value
    display_set_pks = c.add_cases_to_reader_study(
        reader_study="reader-study",
        display_sets=[
            {
                "metrics-json-file": {"foo": "bar"},
            },
        ],
    )

    display_set = c.reader_studies.display_sets.detail(pk=display_set_pks[0])

    assert display_set.values[0].interface.slug == "metrics-json-file"
    assert cast(dict, display_set.values[0].value)["foo"] == "bar"

    # Update the structured value
    updated_display_set = c.update_display_set(
        display_set_pk=display_set.pk,
        values={
            "metrics-json-file": {"foo2": "bar2"},
        },
    )

    assert updated_display_set.values is not None

    assert (
        cast(dict, updated_display_set.values[0].value)["foo2"] == "bar2"
    ), "Sanity, values are applied directly"

    display_set = c.reader_studies.display_sets.detail(pk=display_set_pks[0])
    assert display_set.values[0].interface.slug == "metrics-json-file"
    assert cast(dict, display_set.values[0].value)["foo2"] == "bar2"


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
    def check_image(socket_value, expected_name):
        image = get_image(c, socket_value.image)
        assert image.name == expected_name

    def check_annotation(socket_value, expected):
        assert socket_value.value == expected

    @recurse_call
    def check_file(socket_value, expected_name):
        response = c(url=socket_value.file, follow_redirects=True)
        assert response.url.path.endswith(expected_name)

    for display_set_pk, display_set in zip(
        added_display_sets,
        display_sets,
        strict=True,
    ):

        ds = get_complete_socket_value_set(
            get_func=partial(
                c.reader_studies.display_sets.detail, pk=display_set_pk
            ),
            complete_num_sv=len(display_set),
        )

        for socket_slug, value in display_set.items():
            socket_value = [
                sv for sv in ds.values if sv.interface.slug == socket_slug
            ][0]

            if socket_value.interface.super_kind == "Image":
                file_name = value[0].name
                check_image(socket_value, file_name)
            elif socket_value.interface.kind == "2D bounding box":
                check_annotation(socket_value, value)
                pass
            elif socket_value.interface.super_kind == "File":
                file_name = value[0].name
                check_file(socket_value, file_name)


def test_add_cases_to_reader_study_invalid_socket(local_grand_challenge):
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


def test_add_cases_to_archive_invalid_socket(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    archive_items = [
        {
            "very-specific-medical-image": [
                Path(__file__).parent / "testdata" / "image10x10x101.mha"
            ]
        },
    ]

    with pytest.raises(ValueError) as e:
        c.add_cases_to_archive(archive="archive", archive_items=archive_items)

    assert str(e.value) == (
        "very-specific-medical-image is not an existing interface. "
        "Please provide one from this list: "
        "https://grand-challenge.org/components/interfaces/inputs/"
    )
