from contextlib import nullcontext
from pathlib import Path

import pytest

from gcapi.upload_sources import (
    FileCIVSource,
    ImageCIVSource,
    TooManyFiles,
    ValueCIVSource,
)
from tests.factories import SimpleImageFactory

TESTDATA = Path(__file__).parent / "testdata"


@pytest.mark.parametrize(
    "source,context",
    (
        (TESTDATA / "test.json", nullcontext()),
        ([TESTDATA / "test.json"], nullcontext()),
        (str(TESTDATA / "test.json"), nullcontext()),
        ([str(TESTDATA / "test.json")], nullcontext()),
        (
            [TESTDATA / "test.json", TESTDATA / "test.json"],
            pytest.raises(TooManyFiles),
        ),
        ("I DO NOT EXIST", pytest.raises(FileNotFoundError)),
        (["I DO NOT EXIST"], pytest.raises(FileNotFoundError)),
        (["I DO NOT EXIST", "I DO NOT EXIST"], pytest.raises(TooManyFiles)),
    ),
)
def test_file_source_validation(source, context):
    with context:
        FileCIVSource(source)


@pytest.mark.parametrize(
    "source,context",
    (
        (TESTDATA / "image10x10x101.mha", nullcontext()),
        (
            [TESTDATA / "image10x10x10.mhd", TESTDATA / "image10x10x10.zraw"],
            nullcontext(),
        ),
        (SimpleImageFactory(), nullcontext()),
    ),
)
def test_image_file_source_validation(source, context):
    with context:
        ImageCIVSource(source)


@pytest.mark.parametrize(
    "source,context",
    (
        (TESTDATA / "test.json", nullcontext()),
        ([TESTDATA / "test.json"], nullcontext()),
        (
            [TESTDATA / "test.json", TESTDATA / "test.json"],
            pytest.raises(TooManyFiles),
        ),
        (TESTDATA / "invalid_test.json", pytest.raises(ValueError)),
        ({"foo": "bar"}, nullcontext()),
        (1, nullcontext()),
        (object(), pytest.raises(TypeError)),
    ),
)
def test_value_source_validation(source, context):
    with context:
        ValueCIVSource(source)
