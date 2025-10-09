# Copilot Instructions for rse-gcapi

## Project Overview
- **Purpose:** Python client for interacting with the [grand-challenge.org](https://grand-challenge.org/documentation/grand-challenge-api/) REST API.
- **Main Components:**
  - `gcapi/`: Core client logic, API base, models, exceptions, transport, CLI.
  - `tests/`: Pytest-based unit and integration tests, with factories and test utilities.
  - `docs/`: MkDocs documentation, including user guides and API usage examples.

## Architecture & Patterns
- **Client Structure:**
  - `client.py` and `apibase.py` implement the main API client and base request logic.
  - Models in `models.py` and `model_base.py` represent API resources.
  - Error handling is centralized in `exceptions.py`.
  - Transport and retry logic in `transports.py` and `retries.py`.
- **CLI:**
  - `cli.py` provides command-line access to API features.
- **Testing:**
  - Use `pytest` for running tests

## Developer Workflows
**Install & Environment:**
  - Use [`uv`](https://github.com/astral-sh/uv) for fast, reliable Python environment management.
  - Create a virtual environment: `uv venv .venv`
  - Install dependencies: `uv pip install -r requirements.txt` (or use `pyproject.toml` if supported)
  - Install the package: `uv pip install .` or for editable installs: `uv pip install -e .`
**Test:**
  - Run all tests: `pytest tests/`
  - You can also use `uv pip install pytest` to install pytest if not present.
**Build Docs:**
  - Build documentation with `mkdocs build` (install with `uv pip install mkdocs`).
**Linting & Formatting:**
  - Use [`pre-commit`](https://pre-commit.com/) to automate code style and linting checks. Install with `uv pip install pre-commit`.
  - Set up hooks: `pre-commit install`
  - Run all checks manually: `pre-commit run --all-files`
  - Code style: [black](https://github.com/psf/black) (`uv pip install black`).
  - Linting: Use `flake8` (`uv pip install flake8`).

## Conventions & Integration
- **API Usage:**
  - All API interactions go through the client in `gcapi/client.py`.
  - Models are instantiated from API responses.
- **Error Handling:**
  - Always catch and handle exceptions from `gcapi/exceptions.py`.
- **External Dependencies:**
  - Defined in `pyproject.toml` and `setup.cfg`.
- **Documentation:**
  - User and developer docs in `docs/`.
  - Update `README.md` and `mkdocs.yml` for major changes.
- **Convenience Methods:**
  - Directly under client class for common tasks.

---

**Feedback:** If any section is unclear or missing, please specify what needs improvement or additional detail.
