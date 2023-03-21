import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from datamodel_code_generator import DataModelType, PythonVersion, generate


def main() -> int:
    json_schema = httpx.get(
        "https://gc.localhost/api/schema/",
        verify=False,
        headers={"accept": "application/json"},
    )

    with TemporaryDirectory() as temporary_directory_name:
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
            field_include_all_keys=True,
            output_model_type=DataModelType.DataclassesDataclass,
            target_python_version=PythonVersion.PY_38,
        )

        with open(Path(__file__).parent / "gcapi" / "models.py", "w") as f:
            f.write(
                output.read_text().replace(
                    "from dataclasses import dataclass, field",
                    "from pydantic.dataclasses import dataclass",
                )
            )

    return 0


if __name__ == "__main__":
    raise (SystemExit(main()))
