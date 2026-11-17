---
goal: "Per-tenant knowledge base editable from the back office: document map, whole documents, hybrid search"
branch: main
started: 2026-11-17T11:44:36.328Z
start_sha: 524da8e95b67f48a97077d01c291989f35bf16ab
status: closed
ended: 2026-11-17T18:40:55.061Z
---
# Per-tenant knowledge base editable from the back office: document map, whole documents, hybrid search

## Done
- Per-tenant versioned knowledge base editable from the back office (data layer, hybrid retriever, admin API, document map, back office page, eval, ADR-0022)
- 7 review findings fixed
- Merged as PRs 179,181,182,183,188,189,190,191

## Decisions

## Open / blocked
- Identity gate for anonymous policy questions undecided

## Next
- Add OLLAMA_NUM_CTX=16384 to .env.example
- Anonymous questions about terms, privacy and refunds are identity-gated: decide and build the fix
- Playwright node module in the akatsuki cache for verify shot
- Clean remote stack/* branches

## Changes (from git)
Commits:
- b4240c1 Evaluate the per-tenant knowledge base and record ADR-0022 (#191)
- f23b2c7 Back office: knowledge base page (#190)
- 9439b64 Back office: knowledge base API client and markdown preview helpers (#189)
- 67d44b3 Let the agent read a document map and open whole documents (#188)
- bca01b2 Add the knowledge base admin API (#183)
- 430966f Cache each tenant's document map and list plans in the admin API (#182)
- dd8805d Per-tenant, versioned knowledge base data layer and tenant-scoped hybrid retrieval (#181)
- 33f02ec Pass an explicit context size to Ollama (#179)

Diff: 81 files changed, 4341 insertions(+), 304 deletions(-)

Tests touched: `backend/tests/evaluation/test_metrics.py`, `backend/tests/evaluation/test_retrieval_eval.py`, `backend/tests/integration/conftest.py`, `backend/tests/integration/test_api_admin_kb.py`, `backend/tests/integration/test_api_admin_plans.py`, `backend/tests/integration/test_db_seed.py`, `backend/tests/integration/test_eval_sessions.py`, `backend/tests/integration/test_rag_catalog.py`, `backend/tests/integration/test_rag_ingestion.py`, `backend/tests/integration/test_retriever.py`, `backend/tests/integration/test_tools_documents.py`, `backend/tests/integration/test_tools_knowledge_base.py`, `backend/tests/unit/test_admin_routes.py`, `backend/tests/unit/test_agent_document_tools_graph.py`, `backend/tests/unit/test_agent_llm_tools_documents.py`
