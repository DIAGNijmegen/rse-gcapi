import os
from typing import Dict

from setuptools import find_packages, setup

NAME = "gcapi"

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

requirements = [
    "Click>=6.0",
    "Requests",
    "jsonschema[format_nongpl]>=3.0",
]

test_requirements = [
    "pytest",
    "pyyaml",
    "docker-compose-wait",
    "pytest-cov",
]

about: Dict[str, str] = {}
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, NAME, "__version__.py")) as f:
    exec(f.read(), about)

setup(
    author="James Meakin",
    author_email="code@jmsmkn.com",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    description="Python client for the grand-challenge.org API",
    entry_points={"console_scripts": ["gcapi=gcapi.cli:main"]},
    extras_require={"test": test_requirements},
    install_requires=requirements,
    license="Apache Software License 2.0",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="gcapi",
    name=NAME,
    packages=find_packages(include=["gcapi"]),
    package_data={"gcapi": ["schemas/*"]},
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/DIAGNijmegen/rse-gcapi",
    version=about["__version__"],
    zip_safe=False,
)
