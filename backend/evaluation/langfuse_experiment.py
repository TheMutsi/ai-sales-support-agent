"""Runs the evaluation suite as a Langfuse dataset experiment.

The local backend (`run_eval.run_suite`) only writes a JSON report. This one
runs the same cases, through the same `/api/chat` client and the same
evaluators, as a Langfuse *experiment*: every case is a dataset item, every
invocation of the suite is a named dataset run, and every metric is a score on
that run's item. Langfuse can then put runs side by side (which metric moved,
which cases flipped), which a folder of JSON reports cannot.

The JSONL files stay the source of truth. They are upserted into Langfuse
before each run under deterministic item ids, so editing a case updates its
item instead of adding a duplicate.
"""

import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from langfuse import Evaluation, Langfuse, propagate_attributes

from .chat_client import run_chat_turn
from .metrics import Evaluator, pass_rates_by_metric, score_case
from .schemas import CaseResult, ChatTurn, EvalCase

DATASET_NAME_PREFIX = "acmeflow-eval"


def dataset_name_for(path: Path) -> str:
    """`evaluation/heldout.jsonl` -> `acmeflow-eval/heldout`. Langfuse shows the
    `/` as a folder, keeping the dev and held-out sets apart."""
    return f"{DATASET_NAME_PREFIX}/{path.stem}"


def dataset_item_id(dataset_name: str, case_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_name}/{case_id}"))


def dataset_item_fields(case: EvalCase) -> dict[str, Any]:
    """Splits a case into what the agent sees (`input`) and what it is
    scored against (`expected_output`), so the Langfuse UI shows them apart."""
    return {
        "input": {
            "customer_email": case.customer_email,
            "messages": [message.model_dump() for message in case.messages],
        },
        "expected_output": case.model_dump(
            mode="json", exclude={"id", "scenario", "customer_email", "messages", "notes"}
        ),
        # `notes` stays out: the SDK copies item metadata onto every span and
        # drops values over 200 characters, which most notes exceed.
        "metadata": {"case_id": case.id, "scenario": case.scenario.value},
    }


def to_evaluations(result: CaseResult) -> list[Evaluation]:
    return [
        Evaluation(
            name=metric.metric.value,
            value=1.0 if metric.passed else 0.0,
            data_type="BOOLEAN",
            comment=metric.detail or None,
        )
        for metric in result.metrics
    ]


def run_level_evaluations(results: Sequence[CaseResult], total_cases: int) -> list[Evaluation]:
    """Aggregate scores attached to the dataset run itself, so runs can be
    compared on one number per metric without opening every item. Errored
    cases count against `cases_fully_passed_rate`, never silently for it."""
    evaluations = [
        Evaluation(name=f"pass_rate.{metric.value}", value=rate.pass_rate, comment=f"n={rate.n}")
        for metric, rate in pass_rates_by_metric(results).items()
    ]
    passed = sum(result.passed for result in results)
    evaluations.append(
        Evaluation(
            name="cases_fully_passed_rate",
            value=passed / total_cases if total_cases else 0.0,
            comment=f"{passed}/{total_cases} ({total_cases - len(results)} errored)",
        )
    )
    return evaluations


class LangfuseExperimentRunner:
    """One experiment run over a list of cases.

    Scoring happens in the Langfuse evaluator, not the task, so the judge's
    latency and errors are recorded on the evaluator span rather than inflating
    the agent's. Each `CaseResult` is also kept here, so the run produces the
    same local JSON report as the local backend.
    """

    def __init__(
        self,
        client: Langfuse,
        http: httpx.Client,
        base_url: str,
        customer_ids: dict[str, uuid.UUID],
        evaluators: Sequence[Evaluator],
    ) -> None:
        self._client = client
        self._http = http
        self._base_url = base_url
        self._customer_ids = customer_ids
        self._evaluators = evaluators
        self._cases: dict[str, EvalCase] = {}
        self._results: dict[str, CaseResult] = {}

    def run(
        self,
        cases: Sequence[EvalCase],
        dataset_name: str,
        run_name: str,
        metadata: dict[str, str],
    ) -> tuple[list[CaseResult], list[str], str | None]:
        """Returns `(results, errored_case_ids, dataset_run_url)`."""
        self._cases = {case.id: case for case in cases}
        self._results = {}

        self._client.create_dataset(name=dataset_name)
        items = [
            self._client.create_dataset_item(
                dataset_name=dataset_name,
                id=dataset_item_id(dataset_name, case.id),
                **dataset_item_fields(case),
            )
            for case in cases
        ]
        outcome = self._client.run_experiment(
            name=dataset_name,
            run_name=run_name,
            data=items,
            task=self._task,
            evaluators=[self._evaluate],
            run_evaluators=[self._evaluate_run],
            # The task is a blocking HTTP call, so the SDK's async scheduler
            # could not overlap items anyway; 1 makes the order explicit.
            max_concurrency=1,
            metadata=metadata,
        )

        results = [self._results[case.id] for case in cases if case.id in self._results]
        errored = [case.id for case in cases if case.id not in self._results]
        return results, errored, outcome.dataset_run_url

    def _task(self, *, item: Any, **_: Any) -> dict[str, Any]:
        case = self._cases[item.metadata["case_id"]]
        conversation_id = uuid.uuid4()
        try:
            # The API puts the agent's own trace in the session named by
            # `conversation_id`; sharing it links this item to that trace.
            with propagate_attributes(session_id=str(conversation_id)):
                turn = run_chat_turn(
                    self._http,
                    self._base_url,
                    self._customer_ids[case.customer_email],
                    case,
                    conversation_id=conversation_id,
                )
        except Exception as exc:
            # Langfuse only logs a failed item; say which case it was.
            print(f"[{case.id}] ERROR: {exc}", file=sys.stderr)
            raise
        return turn.model_dump(mode="json")

    def _evaluate(self, *, output: dict[str, Any], metadata: dict[str, Any], **_: Any):
        case = self._cases[metadata["case_id"]]
        try:
            result = score_case(case, ChatTurn.model_validate(output), self._evaluators)
        except Exception as exc:
            print(f"[{case.id}] ERROR while scoring: {exc}", file=sys.stderr)
            raise
        self._results[case.id] = result
        return to_evaluations(result)

    def _evaluate_run(self, **_: Any) -> list[Evaluation]:
        return run_level_evaluations(list(self._results.values()), len(self._cases))
