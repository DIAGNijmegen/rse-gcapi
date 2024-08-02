# Grand Challenge API Client

[![CI](https://github.com/DIAGNijmegen/rse-gcapi/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DIAGNijmegen/rse-gcapi/actions/workflows/ci.yml?query=branch%3Amain)
[![PyPI](https://img.shields.io/pypi/v/gcapi)](https://pypi.org/project/gcapi/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/gcapi)](https://pypi.org/project/gcapi/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Python client for the grand-challenge.org REST API

  - Free software: Apache Software License 2.0

## Features

This client library is a handy way to interact with the REST API for
grand-challenge.org from python, and provides some convenience methods.
Documentation and examples can be found on [Grand
Challenge](https://grand-challenge.org/documentation/grand-challenge-api/).

## Tests
This client is tested using the `tox` framework. This enables testing
the client in various python-version environments.

For example, running a specific `your_test` for only the python 3.9
environment can be done as follows:
```bash
tox -e py39 -- -k your_test
```
