import pytest

from task_printer.web import schemas as s


def _limits(**over):
    base = {
        "MAX_SECTIONS": 50,
        "MAX_TASKS_PER_SECTION": 50,
        "MAX_TASK_LEN": 200,
        "MAX_CATEGORY_LEN": 100,
    }
    base.update(over)
    return {"limits": base}


def test_schema_accepts_valid_payload():
    data = {
        "sections": [
            {
                "category": "Home",
                "tasks": [
                    {"text": "Dishes", "flair_type": "icon", "flair_value": "cleaning"},
                    {"text": "", "flair_type": "none"},  # allowed; route skips empty
                ],
            }
        ],
        "options": {"tear_delay_seconds": 2.5},
    }
    req = s.JobSubmitRequest.model_validate(data, context=_limits())
    assert len(req.sections) == 1
    assert req.sections[0].category == "Home"
    assert req.sections[0].tasks[0].flair_type == "icon"
    assert req.options and req.options.tear_delay_seconds == 2.5


def test_schema_limits_enforced_by_context():
    data = {
        "sections": [
            {"category": "A", "tasks": [{"text": "T"}]},
            {"category": "B", "tasks": [{"text": "T"}]},
        ]
    }
    with pytest.raises(Exception):
        s.JobSubmitRequest.model_validate(data, context=_limits(MAX_SECTIONS=1))


def test_schema_flair_type_invalid():
    data = {
        "sections": [
            {"category": "A", "tasks": [{"text": "T", "flair_type": "bad"}]}
        ]
    }
    with pytest.raises(Exception):
        s.JobSubmitRequest.model_validate(data, context=_limits())


def test_options_clamping_and_ignore_negative():
    # Negative becomes None; >60 clamps to 60
    req = s.JobSubmitRequest.model_validate(
        {"sections": [{"category": "A", "tasks": [{"text": "T"}]}], "options": {"tear_delay_seconds": -1}},
        context=_limits(),
    )
    assert req.options is None or req.options.tear_delay_seconds is None

    req2 = s.JobSubmitRequest.model_validate(
        {"sections": [{"category": "A", "tasks": [{"text": "T"}]}], "options": {"tear_delay_seconds": 120}},
        context=_limits(),
    )
    assert req2.options and req2.options.tear_delay_seconds == 60.0

