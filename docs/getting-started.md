---
hide:
  - navigation
---

# Getting started with gcapi

## Install gcapi

First, let's install the newest version of [gcapi](https://pypi.org/project/gcapi/) with pip.

```bash
$ pip install gcapi
```

## Retrieve a personal API token

In order to start using gcapi you need to get a personal Grand-Challenge API token. An API token is a unique identifier that is used to authenticate you on the API.

A full token looks like this:
```Python
"df41b403eac8ca19c80f04c3f129809f5e9635f65fbead1aa3cafccc7e865c5a"
```

You can generate the token yourself [on Grand Challenge](https://grand-challenge.org/settings/api-tokens/). After logging in, navigate to *Your Profile ➞ Manage API Tokens* and click on *Create a Token*. Once you click *Save*, the token will be generated for you and displayed in a blue ribbon at the top of the page.

You will only be able to see this token once, so store it safely in a password manager for later use. Please treat your API token like a password and remove the key if necessary.

## Initiate your client

Import the necessary library:

```python
import gcapi
```

Then add your personal Grand-Challenge [API token](https://grand-challenge.org/settings/api-tokens/) and initiate the client:

```python
token = 'df41b4...'
client = gcapi.Client(token=token)
```

You can then use the client to interact with Grand Challenge.

Any request made to Grand Challenge will have the token added for authentication.

## On object identifiers

To interact with an algorithm, reader study, archive or any other object on Grand Challenge, you must have the proper identifier of that object. Identifiers come in the shape of a primary key, a slug, or an API URL.

### Primary keys
Primary keys ('pk') are very common in databases and are used to identify specific rows in a table.

Typically, these can be a UUID (e.g. `"4a46b539-119b-4889-90bf-18818ffa3dd8"`) but in some rare cases a simple integer (e.g. `42`).

### Slugs
Slugs are human-readable identifiers and are typically built from the name of your archive, algorithm, or reader study on Grand Challenge. They can be found in the URL of the respective pages on Grand Challenge.

For instance, if you would like to identify the algorithm at `https://grand-challenge.org/algorithms/corads-ai/`, the slug of the algorithm would be `"corads-ai"`.

### API URLs
When retrieving objects from Grand Challenge that, in turn, reference other objects these references are commonly made via the use of an API URL.

For instance, a reader-study `Answer` will reference the display set it belongs to with:
`"https://grand-challenge.org/api/v1/reader-studies/display-sets/41b79371-7bdc-45df-8e00-add3982f16b9/"`

## Access rights

To interact with an algorithm, reader study, archive or other objects on Grand Challenge, you must have the proper access rights. If you do not have the proper access rights the Grand Challenge API will often report back it simply cannot find the object in question.

Unless you are the **editor of the object**, you will first need to request access to the desired algorithm/reader study/archive.

Requesting access can be done by navigating to the respective object page on Grand Challenge, find and press the **Request access** button.

!!! note
    Responding to an access request is generally a manual step for the object owners and might take a couple of hours! Please be patient.
