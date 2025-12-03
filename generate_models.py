import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from datamodel_code_generator import (
    DataModelType,
    InputFileType,
    PythonVersion,
    generate,
)

DEPRECATED_FIELDS = {
    ("HyperlinkedImage", "patient_id"),
    ("HyperlinkedImage", "patient_name"),
    ("HyperlinkedImage", "patient_birth_date"),
    ("HyperlinkedImage", "patient_age"),
    ("HyperlinkedImage", "patient_sex"),
    ("HyperlinkedImage", "study_date"),
    ("HyperlinkedImage", "study_instance_uid"),
    ("HyperlinkedImage", "series_instance_uid"),
    ("HyperlinkedImage", "study_description"),
    ("HyperlinkedImage", "series_description"),
    ("Question", "help_text"),
    ("Question", "question_text"),
    ("Question", "empty_answer_confirmation_label"),
    ("ReaderStudy", "help_text"),
    ("ReaderStudy", "title"),
    ("DisplaySet", "title"),
}


def rewrite_schema(schema):
    for model, field in DEPRECATED_FIELDS:
        model_schema = schema["components"]["schemas"][model]
        model_schema["properties"].pop(field)

        if "required" in model_schema and field in model_schema["required"]:
            model_schema["required"].remove(field)


def main() -> int:
    json_schema = httpx.get(
        "https://grand-challenge.org/api/schema/",
        headers={"accept": "application/json"},
        timeout=10,
    )

    schema = json_schema.json()

    rewrite_schema(schema=schema)

    with TemporaryDirectory(
        prefix="gcapi_modelgen_"
    ) as temporary_directory_name:
        temporary_directory = Path(temporary_directory_name)
        input = temporary_directory / "schema.json"
        output = temporary_directory / "models.py"

        with open(input, "w") as f:
            f.write(json.dumps(schema))

        generate(
            input,
            output=output,
            strip_default_none=True,
            strict_nullable=True,
            output_model_type=DataModelType.DataclassesDataclass,
            target_python_version=PythonVersion.PY_310,
            input_file_type=InputFileType.OpenAPI,
            aliases={
                # Prevent resolving 'json' fields to 'json_'.
                # This happens because the pydantic BaseModel has a
                # deprecated json() function which makes 'json'
                # technically an invalid field name
                "json": "json",
            },
        )

        with open(Path(__file__).parent / "gcapi" / "models.py", "w") as f:
            text = output.read_text()
            to_replace = "from dataclasses import dataclass"
            if to_replace not in text:
                raise ValueError(
                    "Could not insert dataclass import for pydantic"
                )
            f.write(
                text.replace(
                    to_replace,
                    "from pydantic.dataclasses import dataclass",
                )
            )

    return 0


if __name__ == "__main__":
    raise (SystemExit(main()))
