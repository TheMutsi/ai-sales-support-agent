"""Unit tests for the Langfuse experiment backend. The Langfuse client is a
fake that calls the task and evaluators the way the SDK does, and the chat
endpoint is an `httpx.MockTransport`, so no server is needed."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx

from evaluation.langfuse_experiment import (
    LangfuseExperimentRunner,
    dataset_item_fields,
    dataset_item_id,
    dataset_name_for,
    run_level_evaluations,
)
from evaluation.metrics import evaluate_escalation, evaluate_intent_accuracy
from evaluation.schemas import EvalCase, EvalScenario

_CUSTOMER_EMAIL = "ava.chen@northlightstudio.com"
_CUSTOMER_ID = uuid.uuid4()


def _case(case_id: str, **overrides) -> EvalCase:
    defaults = {
        "id": case_id,
        "scenario": EvalScenario.BILLING_QUESTION,
        "customer_email": _CUSTOMER_EMAIL,
        "messages": [{"role": "user", "content": "Why was I charged twice?"}],
        "expected_intent": "billing_question",
    }
    return EvalCase(**{**defaults, **overrides})


class _FakeLangfuse:
    """Mimics the parts of `Langfuse` the runner uses: dataset upserts and a
    sequential `run_experiment` that feeds each task output to the evaluators."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.run_kwargs: dict = {}
        self.item_scores: list = []
        self.run_scores: list = []

    def create_dataset(self, *, name: str) -> None:
        self.dataset_name = name

    def create_dataset_item(self, *, dataset_name: str, id: str, **fields):
        self.items[id] = fields
        return SimpleNamespace(id=id, dataset_id=dataset_name, **fields)

    def run_experiment(self, *, data, task, evaluators, run_evaluators, **kwargs):
        self.run_kwargs = kwargs
        for item in data:
            try:
                output = task(item=item)
            except Exception:  # noqa: BLE001, S112 - the SDK logs and skips failed items.
                continue
            for evaluator in evaluators:
                self.item_scores += evaluator(
                    input=item.input,
                    output=output,
                    expected_output=item.expected_output,
                    metadata=item.metadata,
                )
        for run_evaluator in run_evaluators:
            self.run_scores += run_evaluator(item_results=[])
        return SimpleNamespace(dataset_run_url="http://langfuse.test/run/1")


def _chat_server(requests: list[dict], fail_on: str | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if fail_on and fail_on in payload["messages"][0]["content"]:
            return httpx.Response(500)
        done = {"conversation_id": payload["conversation_id"], "intent": "billing_question"}
        body = (
            f"event: message\ndata: {json.dumps({'text': 'Here is why.'})}\n\n"
            f"event: done\ndata: {json.dumps(done)}\n\n"
        )
        return httpx.Response(200, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _runner(client: _FakeLangfuse, http: httpx.Client) -> LangfuseExperimentRunner:
    return LangfuseExperimentRunner(
        client,
        http,
        "http://api.test",
        {_CUSTOMER_EMAIL: _CUSTOMER_ID},
        [evaluate_intent_accuracy, evaluate_escalation],
    )


def test_dataset_name_keeps_dev_and_heldout_apart():
    assert dataset_name_for(Path("evaluation/dataset.jsonl")) == "acmeflow-eval/dataset"
    assert dataset_name_for(Path("evaluation/heldout.jsonl")) == "acmeflow-eval/heldout"


def test_dataset_item_id_is_stable_per_dataset_and_case():
    assert dataset_item_id("a", "case-1") == dataset_item_id("a", "case-1")
    assert dataset_item_id("a", "case-1") != dataset_item_id("b", "case-1")


def test_dataset_item_fields_separate_input_from_expectations():
    fields = dataset_item_fields(_case("billing-001", notes="double charge"))
    assert fields["input"] == {
        "customer_email": _CUSTOMER_EMAIL,
        "messages": [{"role": "user", "content": "Why was I charged twice?"}],
    }
    assert fields["expected_output"]["expected_intent"] == "billing_question"
    assert "messages" not in fields["expected_output"]
    assert fields["metadata"] == {"case_id": "billing-001", "scenario": "billing_question"}


def test_run_scores_every_case_and_links_the_session():
    client, requests = _FakeLangfuse(), []
    cases = [_case("billing-001"), _case("billing-002", expected_intent="refund_request")]

    results, errored, run_url = _runner(client, _chat_server(requests)).run(
        cases, "acmeflow-eval/dataset", "abc123 run", {"git_revision": "abc123"}
    )

    assert [r.case_id for r in results] == ["billing-001", "billing-002"]
    assert [r.passed for r in results] == [True, False]
    assert errored == []
    assert run_url == "http://langfuse.test/run/1"
    assert len(client.items) == 2
    assert client.run_kwargs["run_name"] == "abc123 run"
    # The conversation id is chosen client-side, so the item's session is
    # the same one the API uses for the agent's own trace.
    assert all(uuid.UUID(payload["conversation_id"]) for payload in requests)
    scores = {(s.name, s.value) for s in client.item_scores}
    assert ("intent_accuracy", 1.0) in scores
    assert ("intent_accuracy", 0.0) in scores


def test_failed_case_is_reported_as_errored_not_dropped():
    client = _FakeLangfuse()
    cases = [
        _case("billing-001"),
        _case("billing-002", messages=[{"role": "user", "content": "boom"}]),
    ]

    results, errored, _ = _runner(client, _chat_server([], fail_on="boom")).run(
        cases, "acmeflow-eval/dataset", "run", {}
    )

    assert [r.case_id for r in results] == ["billing-001"]
    assert errored == ["billing-002"]
    fully_passed = next(s for s in client.run_scores if s.name == "cases_fully_passed_rate")
    assert fully_passed.value == 0.5
    assert fully_passed.comment == "1/2 (1 errored)"


def test_run_level_evaluations_report_one_pass_rate_per_metric():
    client = _FakeLangfuse()
    results, _, _ = _runner(client, _chat_server([])).run(
        [_case("billing-001")], "acmeflow-eval/dataset", "run", {}
    )

    names = {e.name for e in run_level_evaluations(results, total_cases=1)}
    assert names == {
        "pass_rate.intent_accuracy",
        "pass_rate.escalation_correctness",
        "cases_fully_passed_rate",
    }
