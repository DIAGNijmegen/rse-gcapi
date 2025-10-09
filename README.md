# Grand Challenge API Client

Python client for the grand-challenge.org REST API

[![CI](https://github.com/DIAGNijmegen/rse-gcapi/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DIAGNijmegen/rse-gcapi/actions/workflows/ci.yml?query=branch%3Amain)
[![PyPI](https://img.shields.io/pypi/v/gcapi)](https://pypi.org/project/gcapi/)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FDIAGNijmegen%2Frse-gcapi%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Features

This client library is a handy way to interact with the REST API for
grand-challenge.org from python, and provides some convenience methods.

You can use the libarary to automate things like:

* Uploading values as Display Sets in a Reader Study
* Uploading values as Archive Items in an Archive
* Uploading values for an algorithm to predict on
* Downloading results from an algorithm prediction
