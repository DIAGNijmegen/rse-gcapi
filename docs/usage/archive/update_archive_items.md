

## Update the **content** of archive items

To update the contents of a archive items you can use the convenience function: [Client.update_archive_item][gcapi.client.Client.update_archive_item].

### Example

First, retrieve the archive items from your archive:

```python
archive = client.archives.detail(slug="my-archive-slug")
archive_items = list(
    client.archive_items.iterate_all(
        params={"archive": archive.pk}
    )
)
```

To then add, for example, a PDF report and a lung volume
value to the first archive item, provide the socket slugs together
with the respective value or file path as follows:

```python
client.update_archive_item(
    display_set_pk=archive_items[0].pk,
    values={
        "report": 'path/on/your/machine/to/the/report'],
        "lung-volume": 1.9,
    },
)
```

!!! warning
    If you provide a value or file for an already **existing socket value** of the archive item, the old value will be **overwritten** by the new one.
