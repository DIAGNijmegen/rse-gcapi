import warnings
from importlib.metadata import version as get_version

import httpx
from packaging import version


def check_version():
    package_name = "gcapi"
    try:
        current_version = get_version(package_name)
        with httpx.Client() as client:
            response = client.get(f"https://pypi.org/pypi/{package_name}/json")
            latest_version = response.json()["info"]["version"]

        if version.parse(current_version) < version.parse(latest_version):
            warnings.warn(
                f"You are using {package_name} version {current_version}. "
                f"However, version {latest_version} is available. You should consider"
                f" upgrading via `pip install --upgrade {package_name}`",
                UserWarning,
                stacklevel=0,
            )
    except Exception:
        # If there's any error in checking the version, we'll silently pass
        # This ensures the import process isn't disrupted
        pass
