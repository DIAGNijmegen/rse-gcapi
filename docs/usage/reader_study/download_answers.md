First, start off by getting the reader study object.  For this you will need either the [pk, slug or api url](../../getting-started.md#on-object-identifiers) of the reader study.

```python
slug = "my-reader-study-slug"
reader_study = client.reader_studies.detail(slug=slug)
```

Then download the answers, depending on what you need.


## Download all answers
```python
all_answers = reader_answers = list(
    client.reader_studies.answers.iterate_all(
        params={"question__reader_study": reader_study.pk}
    )
)
```


## Download your own answers

```python
my_answers = list(
    client.reader_studies.answers.mine.iterate_all(
        params={"question__reader_study": reader_study.pk}
    )
)
```


## Download a reader's answers

If you for instance would like to download only the answers for user `'your-reader'`:
```python
reader_answers = list(
    client.reader_studies.answers.iterate_all(
        params={
            "question__reader_study": reader_study.pk,
            "creator": "your-reader",
        }
    )
)
```


## Download of answers per display set

If you would like to get the answers per display set, you can use the following code snippet.

Firstly, get all the display sets:

```python
display_sets = client.reader_studies.display_sets.iterate_all(
        params={"reader_study": reader_study.pk}
    )
```

Secondly, get the answers per display set:

```python
answers_per_display_set = {}
for display_set in display_sets:
    answers_per_display_set[display_set.pk] = list(
        client.reader_studies.answers.iterate_all(
            params={"display_set": display_set.pk}
        )
    )
```


## Download choice-type Answers

The answers for (multiple) choice type questions contain only the id of the chosen option, not the option title.

If you would like to add the option title to the answers, you can do so by combining information from the reader study questions:

```python
# Create a dictionary of the multiple choice questions with the question's api_url
# as the key, and the options for the question as the value.
# The options contain the readable title.
choice_questions = {
    question.api_url: question
    for question in reader_study.questions
    if question.answer_type in ("Choice", "Multiple choice")
}


# Local function that will add the readable answer to the answer dictionary
# for (multiple) choice questions.
def add_answer_title(answer):
    if answer.question not in choice_questions:
        return answer
    options = choice_questions[answer.question].options
    if isinstance(answer.answer, list):
        # multiple choice
        answer.answer = list(
            o.title for o in options if o.id in answer.answer
        )
    else:
        # choice
        answer.answer= list(
            o.title for o in options if o.id == answer.answer
        )[0]
    return answer


# You can create a list for just the (multiple) choice type questions.
choice_answers_readable = list(
    add_answer_title(a) for a in answers if a.question in choice_questions
)

# Or create a list of readable items for all answers.
answers_readable = list(str(a.answer) for a in answers)
```


## Download image-type Answers
For questions of type Mask the answers are provided as API URLS to images. You can download these as follows:

```python
image_answers = list(a for a in answers if a.answer_image is not None)
for i in image_answers:
    downloaded_files = client.images.download(
        url=i.answer_image, filename=Path("path/to/output")
    )
```
