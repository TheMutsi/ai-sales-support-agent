"""Deterministic scoring for the evaluation suite: pure functions, no I/O.

Each check is an `Evaluator`: it takes a case and the turn the agent
produced, and returns a `MetricResult`, or `None` when the check does not
apply to that case (e.g. upgrade eligibility on a refund case). `score_case`
runs every registered evaluator; adding a check is one function plus one
entry in `DEFAULT_EVALUATORS`.

Evaluators prefer the structured `ChatTurnSummary` (intent, guardrail flags,
escalation, eligibility) over the response text. Text is only used for
`must_include` / `must_not_include`, as case-insensitive substring checks.
Retrieval quality and tool selection are not scored: neither is observable
through the HTTP API, and they are not approximated from text.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence

from .schemas import (
    CaseResult,
    ChatTurn,
    EvalCase,
    EvalMetric,
    EvalScenario,
    MetricResult,
    PassRate,
)

INJECTION_FLAG_PREFIX = "injection_signal:"

Evaluator = Callable[[EvalCase, ChatTurn], MetricResult | None]


def _terms_present(text: str, terms: Iterable[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() in lowered]


def evaluate_intent_accuracy(case: EvalCase, turn: ChatTurn) -> MetricResult | None:
    if case.expected_intent is None:
        return None
    actual = turn.summary.intent
    return MetricResult(
        metric=EvalMetric.INTENT_ACCURACY,
        passed=actual == case.expected_intent,
        detail=f"expected={case.expected_intent.value} actual={actual}",
    )


def evaluate_input_blocked(case: EvalCase, turn: ChatTurn) -> MetricResult:
    """Always applicable: every case either should or should not have been
    short-circuited by the input guardrail."""
    flags = turn.summary.guardrail_flags
    was_blocked = any(flag.startswith(INJECTION_FLAG_PREFIX) for flag in flags)
    return MetricResult(
        metric=EvalMetric.INPUT_BLOCKED_CORRECTNESS,
        passed=was_blocked == case.expected_input_blocked,
        detail=f"expected={case.expected_input_blocked} actual={was_blocked} flags={flags}",
    )


def evaluate_escalation(case: EvalCase, turn: ChatTurn) -> MetricResult:
    """Always applicable: "this case must not escalate" is an assertion too."""
    summary = turn.summary
    passed = (
        summary.escalated == case.expected_requires_escalation
        and summary.ticket_created == case.expected_ticket_created
    )
    return MetricResult(
        metric=EvalMetric.ESCALATION_CORRECTNESS,
        passed=passed,
        detail=(
            f"expected_escalated={case.expected_requires_escalation} "
            f"actual={summary.escalated}; "
            f"expected_ticket={case.expected_ticket_created} actual={summary.ticket_created}"
        ),
    )


def evaluate_upgrade_eligibility(case: EvalCase, turn: ChatTurn) -> MetricResult | None:
    if case.expected_upgrade_eligible is None:
        return None
    actual = turn.summary.upgrade_eligible
    return MetricResult(
        metric=EvalMetric.UPGRADE_ELIGIBILITY_CORRECTNESS,
        passed=actual == case.expected_upgrade_eligible,
        detail=f"expected={case.expected_upgrade_eligible} actual={actual}",
    )


def evaluate_answer_correctness(case: EvalCase, turn: ChatTurn) -> MetricResult | None:
    if not case.must_include:
        return None
    present = set(_terms_present(turn.response_text, case.must_include))
    missing = [term for term in case.must_include if term not in present]
    return MetricResult(
        metric=EvalMetric.ANSWER_CORRECTNESS,
        passed=not missing,
        detail=f"missing={missing}" if missing else "all required terms present",
    )


def evaluate_hallucination_substring(case: EvalCase, turn: ChatTurn) -> MetricResult | None:
    """Cheap first pass. Negation-blind by design ("we are not X" contains
    "X"); `llm_judge.evaluate_hallucination_llm_judge` is the semantic check."""
    if not case.must_not_include:
        return None
    found = _terms_present(turn.response_text, case.must_not_include)
    return MetricResult(
        metric=EvalMetric.HALLUCINATION_SUBSTRING,
        passed=not found,
        detail=f"forbidden terms found={found}" if found else "no forbidden term found",
    )


DEFAULT_EVALUATORS: tuple[Evaluator, ...] = (
    evaluate_intent_accuracy,
    evaluate_input_blocked,
    evaluate_escalation,
    evaluate_upgrade_eligibility,
    evaluate_answer_correctness,
    evaluate_hallucination_substring,
)


def score_case(
    case: EvalCase,
    turn: ChatTurn,
    evaluators: Sequence[Evaluator] = DEFAULT_EVALUATORS,
) -> CaseResult:
    results = [evaluator(case, turn) for evaluator in evaluators]
    return CaseResult(
        case_id=case.id,
        scenario=case.scenario,
        response_text=turn.response_text,
        summary=turn.summary,
        metrics=[result for result in results if result is not None],
    )


def _pass_rate(outcomes: list[bool]) -> PassRate:
    return PassRate(n=len(outcomes), pass_rate=round(sum(outcomes) / len(outcomes), 3))


def pass_rates_by_metric(results: Iterable[CaseResult]) -> dict[EvalMetric, PassRate]:
    outcomes: defaultdict[EvalMetric, list[bool]] = defaultdict(list)
    for result in results:
        for metric_result in result.metrics:
            outcomes[metric_result.metric].append(metric_result.passed)
    return {metric: _pass_rate(values) for metric, values in sorted(outcomes.items())}


def pass_rates_by_scenario(results: Iterable[CaseResult]) -> dict[EvalScenario, PassRate]:
    outcomes: defaultdict[EvalScenario, list[bool]] = defaultdict(list)
    for result in results:
        outcomes[result.scenario].append(result.passed)
    return {scenario: _pass_rate(values) for scenario, values in sorted(outcomes.items())}
