from evaluation.dataset import load_dataset
from evaluation.retrieval_eval import KB_DATASET_PATH, RankedSection, score_ranker, section_found
from evaluation.schemas import EvalCase, EvalScenario


def _case(case_id: str, sources: list[str], section: str | None = None) -> EvalCase:
    return EvalCase(
        id=case_id,
        scenario=EvalScenario.KB_LOOKUP,
        customer_email="ava.chen@northlightstudio.com",
        messages=[{"role": "user", "content": "question"}],
        expected_sources=sources,
        expected_section=section,
    )


def test_the_knowledge_base_dataset_loads_and_covers_every_kind_of_question():
    cases = load_dataset(KB_DATASET_PATH)

    assert {case.scenario for case in cases} == {
        EvalScenario.KB_LOOKUP,
        EvalScenario.KB_KEYWORD_ONLY,
        EvalScenario.KB_CROSS_REFERENCE,
        EvalScenario.KB_CLAIM_CHECK,
        EvalScenario.KB_IDENTITY_GATE,
    }


def test_a_section_counts_only_inside_the_expected_document_and_within_k():
    case = _case("a", ["t.md"], "Dispute")
    ranked = [RankedSection("other.md", "Dispute resolution"), RankedSection("t.md", "9. Dispute resolution")]

    assert not section_found(ranked, case, 1)
    assert section_found(ranked, case, 2)


def test_scores_average_recall_and_reciprocal_rank_over_the_cases():
    cases = [_case("hit", ["t.md"], "Termination"), _case("miss", ["f.md"])]
    rankings = {
        "hit": [RankedSection("x.md", None), RankedSection("t.md", "10. Termination")],
        "miss": [RankedSection("x.md", None)],
    }

    scores = score_ranker("fake", rankings, cases)

    assert scores.mrr == 0.25
    by_depth = {depth.k: depth for depth in scores.by_depth}
    assert (by_depth[1].recall, by_depth[3].recall) == (0.0, 0.5)
    assert (by_depth[1].section_hit, by_depth[3].section_hit) == (0.0, 1.0)
