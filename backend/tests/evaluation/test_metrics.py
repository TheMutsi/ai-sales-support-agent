"""Unit tests for the deterministic evaluators in `evaluation/metrics.py`.
Pure functions over a case and a turn: no server, database or LLM needed."""

import uuid

from app.schemas.chat import ChatTurnSummary
from evaluation.metrics import (
    evaluate_answer_correctness,
    evaluate_escalation,
    evaluate_hallucination_substring,
    evaluate_input_blocked,
    evaluate_intent_accuracy,
    evaluate_upgrade_eligibility,
    pass_rates_by_metric,
    pass_rates_by_scenario,
    safety_threshold_sweep,
    score_case,
)
from evaluation.schemas import (
    CaseResult,
    ChatTurn,
    EvalCase,
    EvalMetric,
    EvalScenario,
    MetricResult,
)


def _case(**overrides) -> EvalCase:
    defaults = {
        "id": "case-1",
        "scenario": EvalScenario.PRODUCT_QUESTION,
        "customer_email": "ava.chen@northlightstudio.com",
        "messages": [{"role": "user", "content": "hi"}],
    }
    return EvalCase(**{**defaults, **overrides})


def _turn(response_text: str = "text", **summary_overrides) -> ChatTurn:
    summary = ChatTurnSummary(conversation_id=uuid.uuid4(), **summary_overrides)
    return ChatTurn(response_text=response_text, summary=summary)


# --- evaluate_intent_accuracy ---


def test_intent_accuracy_not_applicable_without_expected_intent():
    assert evaluate_intent_accuracy(_case(), _turn()) is None


def test_intent_accuracy_passes_on_match():
    case = _case(expected_intent="product_question")
    result = evaluate_intent_accuracy(case, _turn(intent="product_question"))
    assert result.metric == EvalMetric.INTENT_ACCURACY
    assert result.passed is True


def test_intent_accuracy_fails_on_mismatch():
    case = _case(expected_intent="product_question")
    result = evaluate_intent_accuracy(case, _turn(intent="billing_question"))
    assert result.passed is False
    assert "billing_question" in result.detail


# --- evaluate_input_blocked ---


def test_input_blocked_passes_by_default():
    result = evaluate_input_blocked(_case(), _turn())
    assert result.metric == EvalMetric.INPUT_BLOCKED_CORRECTNESS
    assert result.passed is True


def test_input_blocked_passes_when_expected_and_blocked():
    case = _case(expected_input_blocked=True)
    turn = _turn(input_blocked=True, guardrail_flags=["injection_signal:instruction_override"])
    assert evaluate_input_blocked(case, turn).passed is True


def test_input_blocked_counts_a_safety_judge_refusal():
    """The cascade's second tier blocks without any regex flag."""
    case = _case(expected_input_blocked=True)
    turn = _turn(input_blocked=True, guardrail_flags=["semantic_unsafe_message"])
    assert evaluate_input_blocked(case, turn).passed is True


def test_input_blocked_fails_when_blocked_unexpectedly():
    turn = _turn(input_blocked=True)
    assert evaluate_input_blocked(_case(), turn).passed is False


def test_input_blocked_fails_when_expected_but_not_blocked():
    assert evaluate_input_blocked(_case(expected_input_blocked=True), _turn()).passed is False


# --- evaluate_escalation ---


def test_escalation_passes_when_nothing_happened_and_nothing_expected():
    assert evaluate_escalation(_case(), _turn()).passed is True


def test_escalation_fails_on_unexpected_escalation():
    assert evaluate_escalation(_case(), _turn(escalated=True)).passed is False


def test_escalation_fails_on_unexpected_ticket():
    assert evaluate_escalation(_case(), _turn(ticket_created=True)).passed is False


def test_escalation_passes_when_both_expectations_match():
    case = _case(expected_requires_escalation=True, expected_ticket_created=True)
    assert evaluate_escalation(case, _turn(escalated=True, ticket_created=True)).passed is True


def test_escalation_fails_when_expected_but_missing():
    case = _case(expected_requires_escalation=True, expected_ticket_created=True)
    assert evaluate_escalation(case, _turn()).passed is False


# --- evaluate_upgrade_eligibility ---


def test_upgrade_eligibility_not_applicable_outside_upgrade_cases():
    assert evaluate_upgrade_eligibility(_case(), _turn()) is None


def test_upgrade_eligibility_passes_on_match():
    case = _case(expected_upgrade_eligible=False)
    assert evaluate_upgrade_eligibility(case, _turn(upgrade_eligible=False)).passed is True


def test_upgrade_eligibility_fails_when_not_evaluated():
    case = _case(expected_upgrade_eligible=True)
    assert evaluate_upgrade_eligibility(case, _turn(upgrade_eligible=None)).passed is False


# --- evaluate_answer_correctness ---


def test_answer_correctness_not_applicable_without_must_include():
    assert evaluate_answer_correctness(_case(), _turn()) is None


def test_answer_correctness_is_case_insensitive():
    case = _case(must_include=["Enterprise", "SSO"])
    turn = _turn("That's on our enterprise plan with sso.")
    assert evaluate_answer_correctness(case, turn).passed is True


def test_answer_correctness_reports_every_missing_term():
    case = _case(must_include=["Enterprise", "SSO"])
    result = evaluate_answer_correctness(case, _turn("That's on our Pro plan."))
    assert result.passed is False
    assert "Enterprise" in result.detail
    assert "SSO" in result.detail


# --- evaluate_hallucination_substring ---


def test_hallucination_substring_not_applicable_without_must_not_include():
    assert evaluate_hallucination_substring(_case(), _turn()) is None


def test_hallucination_substring_passes_on_clean_text():
    case = _case(must_not_include=["refund approved"])
    turn = _turn("We can't confirm a refund yet.")
    assert evaluate_hallucination_substring(case, turn).passed is True


def test_hallucination_substring_is_negation_blind():
    """Pins the known limitation that motivates the LLM judge: a correct
    denial still contains the forbidden substring."""
    case = _case(must_not_include=["SOC 2"])
    result = evaluate_hallucination_substring(case, _turn("We are not SOC 2 certified."))
    assert result.passed is False
    assert "SOC 2" in result.detail


# --- score_case ---


def test_score_case_keeps_only_applicable_metrics():
    case = _case(expected_intent="product_question", must_include=["Enterprise"])
    result = score_case(case, _turn("Available on Enterprise.", intent="product_question"))

    metrics = {m.metric for m in result.metrics}
    assert EvalMetric.INTENT_ACCURACY in metrics
    assert EvalMetric.ANSWER_CORRECTNESS in metrics
    assert EvalMetric.HALLUCINATION_SUBSTRING not in metrics
    assert EvalMetric.UPGRADE_ELIGIBILITY_CORRECTNESS not in metrics
    assert result.passed is True


def test_score_case_fails_if_any_metric_fails():
    case = _case(expected_intent="product_question")
    assert score_case(case, _turn(intent="billing_question")).passed is False


def test_score_case_runs_the_given_evaluators_only():
    def always_fails(case, turn):
        return MetricResult(metric=EvalMetric.ANSWER_CORRECTNESS, passed=False)

    result = score_case(_case(), _turn(), evaluators=[always_fails])
    assert [m.metric for m in result.metrics] == [EvalMetric.ANSWER_CORRECTNESS]
    assert result.passed is False


def test_case_result_serializes_its_pass_status():
    """`passed` is derived, and must still reach the JSON report."""
    result = score_case(_case(expected_intent="product_question"), _turn(intent="billing_question"))
    assert result.model_dump()["passed"] is False


# --- pass rates ---


def test_pass_rates_aggregate_by_metric_and_scenario():
    passing = score_case(_case(id="a"), _turn())
    failing = score_case(
        _case(id="b", scenario=EvalScenario.REFUND_REQUEST), _turn(escalated=True)
    )

    by_metric = pass_rates_by_metric([passing, failing])
    assert by_metric[EvalMetric.ESCALATION_CORRECTNESS].n == 2
    assert by_metric[EvalMetric.ESCALATION_CORRECTNESS].pass_rate == 0.5

    by_scenario = pass_rates_by_scenario([passing, failing])
    assert by_scenario[EvalScenario.PRODUCT_QUESTION].pass_rate == 1.0
    assert by_scenario[EvalScenario.REFUND_REQUEST].pass_rate == 0.0


# --- safety_threshold_sweep ---


def _scored(scenario: EvalScenario, safety_confidence: float | None) -> CaseResult:
    return CaseResult(
        case_id="c",
        scenario=scenario,
        response_text="",
        summary=ChatTurnSummary(conversation_id=uuid.uuid4(), safety_confidence=safety_confidence),
        metrics=[],
    )


def test_safety_sweep_counts_cases_below_each_threshold():
    results = [
        _scored(EvalScenario.PROMPT_INJECTION, 0.6),
        _scored(EvalScenario.PROMPT_INJECTION, 0.9),
        _scored(EvalScenario.PRODUCT_QUESTION, 0.85),
        _scored(EvalScenario.BILLING_QUESTION, 1.0),
    ]

    low, high = safety_threshold_sweep(results, [0.7, 0.95])

    assert (low.adversarial_routed, low.adversarial_total) == (1, 2)
    assert (low.benign_routed, low.benign_total) == (0, 2)
    assert (high.adversarial_routed, high.benign_routed) == (2, 1)


def test_safety_sweep_ignores_cases_blocked_before_intent_router():
    results = [_scored(EvalScenario.PROMPT_INJECTION, None)]

    (point,) = safety_threshold_sweep(results, [0.7])

    assert point.adversarial_total == 0
