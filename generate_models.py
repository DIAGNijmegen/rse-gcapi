import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from datamodel_code_generator import generate


def main() -> int:
    json_schema = httpx.get(
        "https://grand-challenge.org/api/schema/",
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
            use_annotated=True,
            field_constraints=True,
            field_include_all_keys=True,
        )

        with open(Path(__file__).parent / "gcapi" / "models.py", "w") as f:
            f.write(output.read_text())

    return 0


if __name__ == "__main__":
    raise (SystemExit(main()))
