"""Pydantic-validation regression tests for `gcapi.models`.

The bug in #268 was that `HyperlinkedJob.exec_duration` / `invoke_duration`
were typed `str`, so the upstream API returning `null` for not-yet-finished
jobs raised `ValidationError` and listing jobs failed. These tests pin
that the duration fields accept `None`.
"""

from pydantic import TypeAdapter

from gcapi.models import (
    Evaluation,
    ExternalEvaluation,
    HyperlinkedJob,
)


def _build_hyperlinked_job_payload(**overrides):
    base = {
        "pk": "00000000-0000-0000-0000-000000000000",
        "url": "https://example.test/jobs/1/",
        "api_url": "https://example.test/api/v1/jobs/1/",
        "algorithm_image": "https://example.test/algos/1/",
        "inputs": [],
        "outputs": [],
        "status": "Provisioned",
        "hanging_protocol": None,
        "optional_hanging_protocols": [],
        "view_content": None,
        "exec_duration": None,
        "invoke_duration": None,
        "algorithm": "https://example.test/algorithms/1/",
    }
    base.update(overrides)
    return base


def test_hyperlinked_job_accepts_null_durations():
    """Regression for #268: API returns null for in-flight jobs."""
    HyperlinkedJob_TA = TypeAdapter(HyperlinkedJob)
    job = HyperlinkedJob_TA.validate_python(_build_hyperlinked_job_payload())
    assert job.exec_duration is None
    assert job.invoke_duration is None


def test_hyperlinked_job_still_accepts_str_durations():
    """Finished jobs return ISO-8601 duration strings; still valid."""
    HyperlinkedJob_TA = TypeAdapter(HyperlinkedJob)
    payload = _build_hyperlinked_job_payload(
        exec_duration="00:01:23.456",
        invoke_duration="00:00:42.000",
    )
    job = HyperlinkedJob_TA.validate_python(payload)
    assert job.exec_duration == "00:01:23.456"
    assert job.invoke_duration == "00:00:42.000"


def test_evaluation_models_accept_null_durations():
    """Same fix applied to Evaluation / ExternalEvaluation; sanity-check
    via TypeAdapter that they don't reject None on the duration fields."""
    for cls in (Evaluation, ExternalEvaluation):
        # We don't construct full payloads here — just confirm the field
        # types declare Optional[str] so a future regression to bare `str`
        # would also break this assertion.
        anns = getattr(cls, "__annotations__", {})
        assert "None" in str(anns["exec_duration"]) or anns["exec_duration"] is type(None) or "Optional" in str(anns["exec_duration"]) or "|" in str(anns["exec_duration"])
        assert "None" in str(anns["invoke_duration"]) or anns["invoke_duration"] is type(None) or "Optional" in str(anns["invoke_duration"]) or "|" in str(anns["invoke_duration"])
