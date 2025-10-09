# generate_docs.py
import dataclasses
import importlib
import inspect
from pathlib import Path


def generate_dataclass_docs(module_name: str, output_file: str):
    mod = importlib.import_module(module_name)
    lines = []
    for name, obj in inspect.getmembers(mod):
        if dataclasses.is_dataclass(obj):
            lines.append(f"## `{name}`")
            lines.append(f"::: {module_name}.{name}")
            lines.append("\toptions:")
            lines.append("\t\tshow_source: false")
            lines.append("\t\tmembers: true\n")

    Path(output_file).write_text("\n".join(lines))


if __name__ == "__main__":
    generate_dataclass_docs("gcapi.models", "docs/client/models.md")
