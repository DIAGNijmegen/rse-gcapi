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


def main() -> int:
    json_schema = httpx.get(
        "https://grand-challenge.org/api/schema/",
        headers={"accept": "application/json"},
    )

    with TemporaryDirectory(
        prefix="gcapi_modelgen_"
    ) as temporary_directory_name:
        temporary_directory = Path(temporary_directory_name)
        input = temporary_directory / "schema.json"
        output = temporary_directory / "models.py"

        with open(input, "w") as f:
            f.write(json.dumps(json_schema.json()))

        generate(
            input,
            output=output,
            base_class="gcapi.model_base.BaseModel",
            strip_default_none=True,
            strict_nullable=True,
            output_model_type=DataModelType.DataclassesDataclass,
            target_python_version=PythonVersion.PY_39,
            input_file_type=InputFileType.OpenAPI,
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
