"""Typed contracts for the evaluation suite: the dataset row, per-metric
results, and the run report.

These live in `evaluation/`, not `app/schemas/`: the application must not
depend on the code that evaluates it. Dependencies point one way only,
`evaluation` -> `app` (it reuses `Intent`, `ChatMessage` and
`ChatTurnSummary`, the same contracts the API exposes).

Every categorical field is a `StrEnum`, so a typo in `dataset.jsonl` fails
validation at load time instead of silently never matching.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field, model_validator

from app.schemas.agent import Intent
from app.schemas.chat import ChatMessage, ChatTurnSummary


class EvalScenario(StrEnum):
    """Why a dataset case exists. Broader than `Intent`: several scenarios
    (prompt injection, ambiguous input, a customer misstating their own plan)
    probe behavior around classification rather than one routing branch, so a
    case records its `expected_intent` separately when one applies."""

    PRODUCT_QUESTION = "product_question"
    PRICING_QUESTION = "pricing_question"
    BILLING_QUESTION = "billing_question"
    TECHNICAL_SUPPORT = "technical_support"
    UPGRADE_REQUEST = "upgrade_request"
    REFUND_REQUEST = "refund_request"
    HUMAN_ESCALATION = "human_escalation"
    UNSUPPORTED = "unsupported"
    PROMPT_INJECTION = "prompt_injection"
    AMBIGUOUS_INPUT = "ambiguous_input"
    WRONG_CUSTOMER_ASSUMPTION = "wrong_customer_assumption"
    TOOL_EDGE_CASE = "tool_edge_case"
    # An anonymous visitor: what they can ask without identifying, and when the assistant
    # must ask them to identify first.
    ANONYMOUS_VISITOR = "anonymous_visitor"


class EvalIdentity(StrEnum):
    """Who the visitor is when the case's last message is sent: logged in as the case's
    customer (the shop vouched for them) or an anonymous visitor."""

    STORE_LOGIN = "store_login"
    ANONYMOUS = "anonymous"


class EvalMetric(StrEnum):
    """Metric names, used both as keys in the JSON report and as Langfuse
    score names, so each name is defined exactly once."""

    INTENT_ACCURACY = "intent_accuracy"
    INPUT_BLOCKED_CORRECTNESS = "input_blocked_correctness"
    IDENTITY_REQUEST_CORRECTNESS = "identity_request_correctness"
    ESCALATION_CORRECTNESS = "escalation_correctness"
    UPGRADE_ELIGIBILITY_CORRECTNESS = "upgrade_eligibility_correctness"
    ANSWER_CORRECTNESS = "answer_correctness"
    HALLUCINATION_SUBSTRING = "hallucination_substring"
    HALLUCINATION_LLM_JUDGE = "hallucination_llm_judge"


class EvalCase(BaseModel):
    """One line of `dataset.jsonl`.

    Customers are referenced by `customer_email` rather than id because
    `Customer.id` is generated at seed time and changes on every reseed; the
    runner resolves emails to ids before the run starts.
    """

    id: str
    scenario: EvalScenario
    identity: EvalIdentity = EvalIdentity.STORE_LOGIN
    # Required for a logged-in case, ignored for an anonymous one.
    customer_email: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)

    expected_intent: Intent | None = None
    expected_requires_escalation: bool = False
    expected_ticket_created: bool = False
    # Whether `input_guardrail_node` should short-circuit the turn. Distinct
    # from `expected_intent=None`: an ambiguous but legitimate message has no
    # fixed intent either, yet must never be blocked.
    expected_input_blocked: bool = False
    # Whether the assistant should ask the visitor to identify, and with which forms.
    # `expected_identity_methods` is only checked when it is set.
    expected_identity_required: bool = False
    expected_identity_methods: list[str] | None = None
    # Only set for upgrade cases. `None` means "not applicable", not "False".
    expected_upgrade_eligible: bool | None = None

    # Case-insensitive substring checks on the final response text.
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)

    notes: str = ""

    @model_validator(mode="after")
    def _logged_in_cases_name_their_customer(self) -> "EvalCase":
        if self.identity is EvalIdentity.STORE_LOGIN and not self.customer_email:
            raise ValueError("a logged-in case needs a customer_email")
        return self

    @model_validator(mode="after")
    def _ends_with_a_user_message(self) -> "EvalCase":
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be from the user: it is the one that is sent.")
        return self


class ChatTurn(BaseModel):
    """What the system under test produced for one case: the final response
    text (after any guardrail correction) and the structured turn summary."""

    response_text: str
    summary: ChatTurnSummary


class HallucinationJudgment(BaseModel):
    """Structured verdict requested from the LLM judge: whether a forbidden
    statement is asserted as fact, as opposed to denied or merely mentioned."""

    asserts_forbidden_claim: bool
    violated_claim: str | None = None
    reasoning: str


class MetricResult(BaseModel):
    metric: EvalMetric
    passed: bool
    detail: str = ""


class CaseResult(BaseModel):
    case_id: str
    scenario: EvalScenario
    # 1-based; a case run with `--trials k` has k results, one per trial.
    trial: int = 1
    response_text: str
    # Kept whole (not just the conversation id) so a failure can be diagnosed
    # from the report alone, e.g. whether the knowledge base tool ever ran.
    summary: ChatTurnSummary
    metrics: list[MetricResult]

    @computed_field
    @property
    def passed(self) -> bool:
        return all(m.passed for m in self.metrics)


class PassRate(BaseModel):
    n: int
    pass_rate: float
    # Wilson 95% interval: unlike the normal approximation it stays inside
    # [0, 1] and is honest at the small n these metrics have.
    ci_low: float
    ci_high: float


class SafetyThresholdPoint(BaseModel):
    """One row of the `safety_confidence` threshold sweep (see
    `metrics.safety_threshold_sweep`)."""

    threshold: float
    adversarial_routed: int
    adversarial_total: int
    benign_routed: int
    benign_total: int


class BaselineComparison(BaseModel):
    """Paired, case-by-case comparison against an earlier report. A case
    counts as passed when it passed every trial in that run."""

    baseline: str
    cases_compared: int
    fixed: list[str]
    broke: list[str]
    # Exact two-sided McNemar test on the discordant cases: the probability
    # of a fixed/broke split at least this lopsided if nothing had changed.
    mcnemar_p: float


class EvalReport(BaseModel):
    run_at: datetime
    dataset: str
    base_url: str
    # "<provider>:<model>" of the hallucination judge, None when it was skipped.
    judge_model: str | None
    # Set only by the `langfuse` backend: one dataset run per trial.
    langfuse_run_urls: list[str] = Field(default_factory=list)
    trials: int = 1
    total_cases: int
    # Cases that passed every trial; with one trial, simply cases that passed.
    cases_fully_passed: int
    # The share of cases passing all `trials` runs (tau-bench's pass^k), the
    # reliability number: a case that passes 2 of 3 times is not reliable.
    pass_hat_k: PassRate
    # Cases that never produced a result (transport or scoring failure). They
    # are excluded from every rate above, so they must be reported explicitly.
    errored_case_ids: list[str]
    by_metric: dict[EvalMetric, PassRate]
    by_scenario: dict[EvalScenario, PassRate]
    safety_threshold_sweep: list[SafetyThresholdPoint]
    baseline_comparison: BaselineComparison | None = None
    cases: list[CaseResult]
