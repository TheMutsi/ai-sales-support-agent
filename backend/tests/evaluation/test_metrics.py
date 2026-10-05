"""Unit tests for the deterministic evaluators in `evaluation/metrics.py`.
Pure functions over a case and a turn: no server, database or LLM needed."""

import json
import uuid

import pytest

from app.schemas.chat import ChatTurnSummary
from evaluation.metrics import (
    compare_to_baseline,
    evaluate_answer_correctness,
    evaluate_escalation,
    evaluate_hallucination_substring,
    evaluate_input_blocked,
    evaluate_intent_accuracy,
    evaluate_upgrade_eligibility,
    load_baseline_outcomes,
    mcnemar_exact_p,
    pass_hat_k,
    pass_rates_by_metric,
    pass_rates_by_scenario,
    safety_threshold_sweep,
    score_case,
    wilson_interval,
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


# --- reliability and paired comparison ---


def _result(case_id: str, passed: bool, trial: int = 1) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        scenario=EvalScenario.PRODUCT_QUESTION,
        trial=trial,
        response_text="",
        summary=_turn().summary,
        metrics=[MetricResult(metric=EvalMetric.INTENT_ACCURACY, passed=passed)],
    )


def test_wilson_interval_matches_the_known_value_and_stays_in_bounds():
    low, high = wilson_interval(50, 55)
    assert (round(low, 3), round(high, 3)) == (0.804, 0.961)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    assert wilson_interval(3, 3)[1] == 1.0


def test_pass_hat_k_requires_every_trial_to_pass():
    results = [
        _result("a", True, 1),
        _result("a", True, 2),
        _result("b", True, 1),
        _result("b", False, 2),
    ]
    rate = pass_hat_k(results)
    assert (rate.n, rate.pass_rate) == (2, 0.5)
    # Per-trial metric rates still count every trial.
    assert pass_rates_by_metric(results)[EvalMetric.INTENT_ACCURACY].n == 4


def test_mcnemar_exact_p():
    assert mcnemar_exact_p(5, 2) == pytest.approx(0.453, abs=1e-3)
    assert mcnemar_exact_p(0, 0) == 1.0
    assert mcnemar_exact_p(10, 0) < 0.01


def test_compare_to_baseline_pairs_cases_present_in_both(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "a", "passed": False},
                    {"case_id": "b", "passed": True},
                    {"case_id": "gone", "passed": True},
                ]
            }
        )
    )
    current = [_result("a", True), _result("b", False), _result("new", True)]

    comparison = compare_to_baseline(current, load_baseline_outcomes(baseline), "baseline")

    assert comparison.cases_compared == 2
    assert (comparison.fixed, comparison.broke) == (["a"], ["b"])
    assert comparison.mcnemar_p == 1.0


def test_a_report_without_per_case_outcomes_is_rejected_clearly(tmp_path):
    old_report = tmp_path / "old.json"
    old_report.write_text(json.dumps({"cases": [{"id": "a", "pass": True}]}))

    with pytest.raises(ValueError, match="cannot be a baseline"):
        load_baseline_outcomes(old_report)
