"""Evaluation runner: drives the real `/api/chat` endpoint over HTTP for every
case in the dataset, scores each turn, and writes a JSON report.

The agent is treated as a black box behind its public API, so a running
server (`uvicorn app.main:app`) and a seeded database are required. The only
direct database access is resolving the dataset's customer emails to ids,
done once up front so a missing customer fails the run before it starts.

Two backends run the same cases through the same evaluators:

- `local` (default): no Langfuse at all. The fast loop while developing.
- `langfuse`: the run is a Langfuse dataset experiment (see
  `langfuse_experiment.py`), comparable run by run in the Langfuse UI. Which
  Langfuse instance it lands in (the local Docker one, or a shared one) is
  decided by the `LANGFUSE_*` settings alone.

Both write the same JSON report.

Usage:
    python -m evaluation.run_eval
    python -m evaluation.run_eval --dataset evaluation/heldout.jsonl --judge-model llama3
    python -m evaluation.run_eval --backend langfuse --judge-model llama3
    python -m evaluation.run_eval --no-llm-judge
"""

import argparse
import subprocess
import sys
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import LLMProvider, get_settings
from app.core.llm import create_chat_model, get_chat_model_name
from app.core.observability import configure_langfuse
from app.db.models import Customer
from app.db.session import SessionLocal

from .chat_client import run_chat_turn
from .dataset import DEFAULT_DATASET_PATH, load_dataset
from .langfuse_experiment import LangfuseExperimentRunner, dataset_name_for
from .llm_judge import make_hallucination_judge
from .metrics import (
    DEFAULT_EVALUATORS,
    Evaluator,
    pass_rates_by_metric,
    pass_rates_by_scenario,
    safety_threshold_sweep,
    score_case,
)
from .schemas import CaseResult, EvalCase, EvalReport

_DEFAULT_RESULTS_DIR = Path(__file__).parent / "results"
_SAFETY_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)


def resolve_customer_ids(session: Session, emails: Iterable[str]) -> dict[str, uuid.UUID]:
    wanted = set(emails)
    rows = session.execute(select(Customer.email, Customer.id).where(Customer.email.in_(wanted)))
    resolved = {email: customer_id for email, customer_id in rows}
    missing = sorted(wanted - resolved.keys())
    if missing:
        raise ValueError(f"customers not found (is the database seeded?): {missing}")
    return resolved


def run_suite(
    cases: Sequence[EvalCase],
    customer_ids: dict[str, uuid.UUID],
    base_url: str,
    evaluators: Sequence[Evaluator],
) -> tuple[list[CaseResult], list[str]]:
    """Runs every case and returns `(results, errored_case_ids)`. A failing
    case is recorded and skipped; it never aborts the rest of the run."""
    results: list[CaseResult] = []
    errored: list[str] = []
    with httpx.Client() as client:
        for case in cases:
            try:
                turn = run_chat_turn(client, base_url, customer_ids[case.customer_email], case)
                result = score_case(case, turn, evaluators)
            except Exception as exc:  # noqa: BLE001 - transport, server and LLM-judge
                # provider errors are heterogeneous; any of them fails this case only.
                print(f"[{case.id}] ERROR: {exc}", file=sys.stderr)
                errored.append(case.id)
                continue

            results.append(result)
            _print_case_result(result)
    return results, errored


def run_langfuse_experiment(
    cases: Sequence[EvalCase],
    customer_ids: dict[str, uuid.UUID],
    base_url: str,
    evaluators: Sequence[Evaluator],
    dataset: Path,
    judge_model: str | None,
) -> tuple[list[CaseResult], list[str], str | None]:
    from langfuse import get_client

    # The Langfuse SDK reads its keys from the process environment, which
    # `configure_langfuse()` populates from `Settings`.
    configure_langfuse()
    client = get_client()
    if not client.auth_check():
        raise SystemExit(f"Langfuse rejected the configured keys ({get_settings().langfuse_host})")

    revision = _git_revision()
    # The agent model is read from this process's settings: the server is
    # assumed to share the same `.env`, as it does in every documented setup.
    agent_model = f"{get_settings().llm_provider}:{get_chat_model_name()}"
    run_name = f"{revision} {agent_model} {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}"
    metadata = {
        "git_revision": revision,
        "agent_model": agent_model,
        "judge_model": judge_model or "skipped",
        "base_url": base_url,
    }
    try:
        with httpx.Client() as http:
            runner = LangfuseExperimentRunner(client, http, base_url, customer_ids, evaluators)
            results, errored, run_url = runner.run(
                cases, dataset_name_for(dataset), run_name, metadata
            )
    finally:
        client.flush()
    for result in results:
        _print_case_result(result)
    return results, errored, run_url


def _git_revision() -> str:
    """Short commit hash, suffixed `-dirty` when the working tree has
    uncommitted changes: a run on edited prompts must not pass for the commit."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def build_report(
    results: list[CaseResult],
    errored_case_ids: list[str],
    dataset: Path,
    base_url: str,
    judge_model: str | None,
    langfuse_run_url: str | None = None,
) -> EvalReport:
    return EvalReport(
        run_at=datetime.now(UTC),
        dataset=str(dataset),
        base_url=base_url,
        judge_model=judge_model,
        langfuse_run_url=langfuse_run_url,
        total_cases=len(results),
        cases_fully_passed=sum(result.passed for result in results),
        errored_case_ids=errored_case_ids,
        by_metric=pass_rates_by_metric(results),
        by_scenario=pass_rates_by_scenario(results),
        safety_threshold_sweep=safety_threshold_sweep(results, _SAFETY_THRESHOLDS),
        cases=results,
    )


def _print_case_result(result: CaseResult) -> None:
    print(f"[{result.case_id}] {'PASS' if result.passed else 'FAIL'} ({result.scenario.value})")
    for metric_result in result.metrics:
        if not metric_result.passed:
            print(f"    {metric_result.metric.value}: {metric_result.detail}")


def _print_summary(report: EvalReport, out_path: Path) -> None:
    print(f"\nRan {report.total_cases} cases, {report.cases_fully_passed} fully passed.")
    print(f"Judge: {report.judge_model or 'skipped'}")
    if report.errored_case_ids:
        print(f"Errored (excluded from all rates): {report.errored_case_ids}")
    for metric, rate in report.by_metric.items():
        print(f"  {metric.value}: {rate.pass_rate:.0%} ({rate.n} applicable)")
    print("safety_confidence threshold -> routed to safety_judge (adversarial / benign):")
    for point in report.safety_threshold_sweep:
        print(
            f"  < {point.threshold:.2f}: {point.adversarial_routed}/{point.adversarial_total}"
            f" / {point.benign_routed}/{point.benign_total}"
        )
    if report.langfuse_run_url:
        print(f"Langfuse run: {report.langfuse_run_url}")
    print(f"Report written to {out_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AcmeFlow agent evaluation suite.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--backend",
        choices=("local", "langfuse"),
        default="local",
        help="local: JSON report only. langfuse: also run as a Langfuse dataset experiment.",
    )
    parser.add_argument(
        "--no-llm-judge",
        action="store_true",
        help="Skip the LLM-judge hallucination check (one extra model call per case).",
    )
    parser.add_argument(
        "--judge-provider",
        default=None,
        choices=get_args(LLMProvider),
        help="Provider for the judge model (default: LLM_PROVIDER).",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Judge model id. Defaults to the agent's own model, which can share its blind "
        "spots; prefer a different one.",
    )
    args = parser.parse_args()
    if args.judge_provider and not args.judge_model:
        parser.error("--judge-provider requires --judge-model")
    return args


def main() -> None:
    args = _parse_args()
    cases = load_dataset(args.dataset)
    with SessionLocal() as session:
        customer_ids = resolve_customer_ids(session, (case.customer_email for case in cases))

    evaluators: list[Evaluator] = list(DEFAULT_EVALUATORS)
    judge_model: str | None = None
    if not args.no_llm_judge:
        provider = args.judge_provider or get_settings().llm_provider
        model = args.judge_model or get_chat_model_name()
        evaluators.append(make_hallucination_judge(create_chat_model(provider, model)))
        judge_model = f"{provider}:{model}"

    run_url: str | None = None
    if args.backend == "langfuse":
        results, errored, run_url = run_langfuse_experiment(
            cases, customer_ids, args.base_url, evaluators, args.dataset, judge_model
        )
    else:
        results, errored = run_suite(cases, customer_ids, args.base_url, evaluators)

    report = build_report(results, errored, args.dataset, args.base_url, judge_model, run_url)
    out_path = args.out or _DEFAULT_RESULTS_DIR / f"{report.run_at:%Y%m%dT%H%M%SZ}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    _print_summary(report, out_path)


if __name__ == "__main__":
    main()
