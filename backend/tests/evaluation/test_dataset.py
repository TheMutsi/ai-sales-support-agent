"""Unit tests for dataset loading and validation."""

import json
from pathlib import Path

import pytest

from evaluation.dataset import DEFAULT_DATASET_PATH, load_dataset


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
    assert len(cases) == 50
