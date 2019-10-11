import pytest
from tests.serializer_helpers import (
    do_test_serializer_valid,
    do_test_serializer_fields,
)
from grandchallenge.patients.serializers import PatientSerializer
from tests.patients_tests.factories import PatientFactory


@pytest.mark.django_db
@pytest.mark.parametrize(
    "serializer_data",
    (
        (
            {
                "unique": True,
                "factory": PatientFactory,
                "serializer": PatientSerializer,
                "fields": ("id", "name"),
            },
        )
    ),
)
class TestSerializers:
    def test_serializer_valid(self, serializer_data):
        do_test_serializer_valid(serializer_data)

    def test_serializer_fields(self, serializer_data):
        do_test_serializer_fields(serializer_data)
