"""Loads and validates `dataset.jsonl`, one `EvalCase` per line.

Validation is strict on purpose: an unknown scenario, metric or intent, or
a duplicate case id, fails the load with the offending line instead of
producing a run that silently scores the wrong thing.
"""

from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from .schemas import EvalCase

DEFAULT_DATASET_PATH = Path(__file__).parent / "dataset.jsonl"


def load_dataset(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(EvalCase.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_number}: invalid eval case: {exc}") from exc

    duplicates = sorted(case_id for case_id, n in Counter(c.id for c in cases).items() if n > 1)
    if duplicates:
        raise ValueError(f"{path}: duplicate case ids: {duplicates}")
    return cases
