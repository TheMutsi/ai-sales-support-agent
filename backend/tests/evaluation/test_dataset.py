"""Unit tests for dataset loading and validation."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.dataset import DEFAULT_DATASET_PATH, HELDOUT_DATASET_PATH, load_dataset
from evaluation.schemas import EvalCase, EvalIdentity, EvalScenario


def _case_line(case_id: str) -> str:
    return json.dumps(
        {
            "id": case_id,
            "scenario": "product_question",
            "customer_email": "ava.chen@northlightstudio.com",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )


def test_load_dataset_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(_case_line("a") + "\n\n" + _case_line("b") + "\n")
    assert [case.id for case in load_dataset(path)] == ["a", "b"]


def test_load_dataset_reports_the_invalid_line(tmp_path: Path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(_case_line("a") + "\n" + '{"id": "b", "scenario": "not_a_scenario"}\n')
    with pytest.raises(ValueError, match=r"dataset\.jsonl:2"):
        load_dataset(path)


def test_load_dataset_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(_case_line("a") + "\n" + _case_line("a") + "\n")
    with pytest.raises(ValueError, match="duplicate case ids"):
        load_dataset(path)


def test_shipped_dataset_is_valid():
    cases = load_dataset(DEFAULT_DATASET_PATH)
    assert len(cases) == 82


def test_heldout_set_does_not_overlap_the_dev_set():
    dev = load_dataset(DEFAULT_DATASET_PATH)
    heldout = load_dataset(HELDOUT_DATASET_PATH)

    def first_messages(cases):
        return {case.messages[0].content.lower() for case in cases}

    assert len(heldout) == 16
    assert not {case.id for case in dev} & {case.id for case in heldout}
    assert not first_messages(dev) & first_messages(heldout)


def test_a_case_must_end_with_a_user_message():
    """The runner sends the last message as the user's turn; an assistant one would be sent
    as if the user had said it, with no error."""
    with pytest.raises(ValidationError, match="last message must be from the user"):
        EvalCase(
            id="c",
            scenario=EvalScenario.PRODUCT_QUESTION,
            customer_email="ava.chen@northlightstudio.com",
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
        )


def test_an_anonymous_case_needs_no_customer():
    case = EvalCase(
        id="a",
        scenario=EvalScenario.PRODUCT_QUESTION,
        identity=EvalIdentity.ANONYMOUS,
        messages=[{"role": "user", "content": "hi"}],
    )

    assert case.customer_email is None


def test_a_logged_in_case_must_name_its_customer():
    with pytest.raises(ValidationError, match="customer_email"):
        EvalCase(
            id="a",
            scenario=EvalScenario.PRODUCT_QUESTION,
            messages=[{"role": "user", "content": "hi"}],
        )


def test_an_order_lookup_case_needs_an_order_to_name():
    base = {
        "id": "o1",
        "scenario": EvalScenario.ORDER_STATUS,
        "identity": EvalIdentity.ORDER_LOOKUP,
        "messages": [{"role": "user", "content": "Where is my order?"}],
    }
    with pytest.raises(ValidationError):
        EvalCase(**base)
    assert EvalCase(**base, customer_email="a@b.test").order_id is None
    assert EvalCase(**base, order_id="n" * 20).customer_email is None
    with pytest.raises(ValidationError):
        EvalCase(**base, order_id="short")


def test_the_order_a_case_names_is_input_to_the_agent_not_part_of_what_it_is_scored_against():
    from evaluation.langfuse_experiment import dataset_item_fields

    case = EvalCase(
        id="o1",
        scenario=EvalScenario.ORDER_STATUS,
        identity=EvalIdentity.ORDER_LOOKUP,
        order_id="n" * 20,
        messages=[{"role": "user", "content": "Where is my order?"}],
    )
    fields = dataset_item_fields(case)

    assert fields["input"]["order_id"] == "n" * 20
    assert "order_id" not in fields["expected_output"]

