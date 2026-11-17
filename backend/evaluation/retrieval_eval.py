import argparse
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.embeddings import get_embeddings
from app.db.models import Tenant
from app.db.seed import DEV_TENANT_API_KEY
from app.db.session import SessionLocal
from app.rag import retriever

from .dataset import load_dataset
from .metrics import recall_at_k, reciprocal_rank
from .schemas import EvalCase

KB_DATASET_PATH = Path(__file__).parent / "kb_dataset.jsonl"
RANKING_DEPTHS = (1, 3, 5)
_DEFAULT_RESULTS_PATH = Path(__file__).parent / "results" / "retrieval.json"


@dataclass(frozen=True)
class RankedSection:
    source: str
    section: str | None


Ranker = Callable[[Session, str, uuid.UUID, int], list[RankedSection]]


def hybrid_ranking(session: Session, query: str, tenant_id: uuid.UUID, top_k: int) -> list[RankedSection]:
    chunks = retriever.search(session, query, tenant_id=tenant_id, top_k=top_k)
    return [RankedSection(chunk.source, chunk.section) for chunk in chunks]


def vector_only_ranking(session: Session, query: str, tenant_id: uuid.UUID, top_k: int) -> list[RankedSection]:
    query_vector = get_embeddings().embed_query(query)
    ranked = retriever._vector_ranking(session, query_vector, tenant_id, None, None)
    seen: set[tuple[uuid.UUID, str | None]] = set()
    sections: list[RankedSection] = []
    for candidate, similarity in ranked:
        if similarity < retriever.DEFAULT_MIN_SIMILARITY:
            continue
        section = retriever._section_title(candidate)
        key = (candidate.document_version_id, section) if section is not None else (candidate.chunk_id, None)
        if key in seen:
            continue
        seen.add(key)
        sections.append(RankedSection(candidate.source, section))
        if len(sections) == top_k:
            break
    return sections


class DepthScores(BaseModel):
    k: int
    recall: float
    section_hit: float | None


class RankerScores(BaseModel):
    ranker: str
    cases: int
    mrr: float
    by_depth: list[DepthScores]


class RetrievalReport(BaseModel):
    run_at: datetime
    dataset: str
    rankers: list[RankerScores]
    misses: dict[str, list[str]]


def section_found(ranked: Sequence[RankedSection], case: EvalCase, k: int) -> bool:
    wanted = case.expected_section.lower() if case.expected_section else ""
    return any(
        item.source in case.expected_sources and item.section is not None and wanted in item.section.lower()
        for item in ranked[:k]
    )


def score_ranker(
    name: str, rankings: dict[str, list[RankedSection]], cases: Sequence[EvalCase]
) -> RankerScores:
    sourced = [case for case in cases if case.expected_sources]
    sectioned = [case for case in sourced if case.expected_section]
    mrr = sum(reciprocal_rank([i.source for i in rankings[c.id]], c.expected_sources) for c in sourced)
    depths = [
        DepthScores(
            k=k,
            recall=round(
                sum(recall_at_k([i.source for i in rankings[c.id]], c.expected_sources, k) for c in sourced)
                / len(sourced),
                3,
            ),
            section_hit=(
                round(sum(section_found(rankings[c.id], c, k) for c in sectioned) / len(sectioned), 3)
                if sectioned
                else None
            ),
        )
        for k in RANKING_DEPTHS
    ]
    return RankerScores(ranker=name, cases=len(sourced), mrr=round(mrr / len(sourced), 3), by_depth=depths)


def run_retrieval_eval(session: Session, tenant_id: uuid.UUID, cases: Sequence[EvalCase]) -> RetrievalReport:
    sourced = [case for case in cases if case.expected_sources]
    rankers: dict[str, Ranker] = {"hybrid": hybrid_ranking, "vector_only": vector_only_ranking}
    scores: list[RankerScores] = []
    misses: dict[str, list[str]] = {}
    for name, ranker in rankers.items():
        rankings = {case.id: ranker(session, case.messages[-1].content, tenant_id, max(RANKING_DEPTHS)) for case in sourced}
        scores.append(score_ranker(name, rankings, sourced))
        misses[name] = [
            case.id
            for case in sourced
            if recall_at_k([i.source for i in rankings[case.id]], case.expected_sources, max(RANKING_DEPTHS)) < 1
        ]
    return RetrievalReport(
        run_at=datetime.now(UTC), dataset=str(KB_DATASET_PATH), rankers=scores, misses=misses
    )


def _print_report(report: RetrievalReport) -> None:
    for scores in report.rankers:
        print(f"{scores.ranker}: {scores.cases} cases, MRR {scores.mrr}")
        for depth in scores.by_depth:
            print(f"  k={depth.k}: recall {depth.recall}, section hit {depth.section_hit}")
        print(f"  misses at k={max(RANKING_DEPTHS)}: {report.misses[scores.ranker]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline retrieval metrics: hybrid against vector only.")
    parser.add_argument("--dataset", type=Path, default=KB_DATASET_PATH)
    parser.add_argument("--out", type=Path, default=_DEFAULT_RESULTS_PATH)
    args = parser.parse_args()
    cases = load_dataset(args.dataset)
    with SessionLocal() as session:
        tenant_id = session.execute(select(Tenant.id).where(Tenant.api_key == DEV_TENANT_API_KEY)).scalar_one()
        report = run_retrieval_eval(session, tenant_id, cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    _print_report(report)


if __name__ == "__main__":
    main()
