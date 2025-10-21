

## Update the **content** of display sets

To update the contents of a display set you can use the convenience function: [Client.update_display_set][gcapi.client.Client.update_display_set].

### Example

First, retrieve the display sets from your reader study:

```Python

reader_study = client.reader_studies.detail(slug="my-reader-study-slug")
display_sets = list(
    client.reader_studies.display_sets.iterate_all(
        params={"reader_study": reader_study.pk}
    )
)
```

To then add, for example, a PDF report and a lung volume
value to the first display set, provide the socket slugs together
with the respective value or file path as follows:

```python
client.update_display_set(
    display_set_pk=display_sets[0].pk,
    values={
        "report": 'path/on/your/machine/to/the/report.pdf'],
        "lung-volume": 1.9,
    },
)
```

!!! warning
    If you provide a value or file for an already **existing socket value** of the display set, the old value will be **overwritten** by the new one.


## Update the **ordering** of display sets

To update the order of a display set (in the example to 10), you can do the following:

```Python
display_set_pk = "41b79371-7bdc-45df-8e00-add3982f16b9"
new_order = 10

client.reader_studies.display_sets.partial_update(
    pk=display_set_pk,
    order=new_order,
)
```
!!! warning
    Using `client.update` here instead of `client.partial_update` would unset the content and title of your display set!

## Update the **titles** of display sets

To update the title of a display set (in the example to "Case 10"), you can do the following:

```Python
display_set_pk = "41b79371-7bdc-45df-8e00-add3982f16b9"
new_title = "Case 10"

client.reader_studies.display_sets.partial_update(
    pk=display_set_pk,
    title=new_title,
)
```

!!! warning
    Using `client.update` here instead of `client.partial_update` would unset the content and order of your display set!
