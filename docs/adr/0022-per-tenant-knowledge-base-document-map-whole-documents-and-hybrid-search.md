# ADR-0022: Per-tenant knowledge base: document map, whole documents and hybrid search

- **Status:** Accepted
- **Introduced in:** the knowledge base wave (versioned documents, hybrid retrieval, document map and `open_documents`, admin API and back office page, evaluation)

## Context

The knowledge base was one global set of documents, found by vector similarity alone and read
as chunks (ADR-0005, ADR-0006). Live runs showed three problems:

- Chunks lose what only a whole document gives. A terms-and-conditions question that needs
  "Sections 4, 7, 8 and 9 survive termination" answered from section 10 without ever reading
  the sections it points to; answers also added claims the document never makes (access until the
  end of the billing period after a termination, a data retention period).
- Vector search alone misses keyword-only queries (an email address, `TLS 1.2`, one product name),
  which embeddings blur.
- A re-ingestion replaced a document's chunks in place: no draft, no rollback, and a failed
  embedding left nothing to roll back to. Each tenant needs its own documents, edited by its
  own staff.

Ollama also truncated prompts without saying so once the prompt grew, which made the model answer
as if the instructions were not there.

## Decision

- **Documents belong to a tenant and have versions.** A document keeps `draft`, `published` and
  `archived` versions (`document_versions`); `documents.published_version_id` points at the one
  that is live. Publishing is atomic: the version's chunks are embedded first, then the pointer
  flips in one transaction, so a failed embedding leaves the live version untouched and writes
  nothing. Chunks exist only for the published version: publishing another version deletes the
  previous one's chunks, and archiving deletes them too. A rollback therefore re-embeds the
  archived version's content, which costs one embedding call and keeps the table at one version of
  chunks per document. `publish_version` only flushes; its callers (the admin routes and `ingest`) commit.
- **A document has an origin.** `documents.origin` is `seed` (loaded from `backend/data/seed/kb`)
  or `admin` (created in the back office, the column default). Re-ingestion archives only seed
  documents whose file is gone, never a back-office document.
- **A document map, not the whole knowledge base, goes in the prompt.** One line per published
  document the visitor may see: id, title, `when_to_use`, estimated size. It is cached per tenant
  (`backend/app/rag/catalog.py`) and invalidated on publish, rollback, archive and a metadata edit. It
  sits after the instructions in the prompt, as reference data and not instructions.
- **`open_documents_tool` reads whole documents.** The model supplies only `document_ids`; the
  tenant and the customer (whose plan is read at call time) are closed over from the graph state when the tool is built, as for
  `search_knowledge_base_tool` (ADR-0006), so it cannot open another tenant's or another plan's
  document. Limits: 3000 tokens per document and 8000 per call; a document over the limit is not
  opened, and the answer lists its section titles so the model can search inside it. Tokens are
  estimated as `ceil(chars / 3)`.
- **`search_knowledge_base_tool` stays, now hybrid.** The vector ranking and a Postgres full-text
  ranking (`simple` configuration, so no language is assumed) are fused with reciprocal rank
  fusion (k = 60). The hit is the whole `##` section its chunk belongs to. A chunk counts as
  relevant only if the full-text query matched or its cosine similarity is at least 0.4: the
  cut ADR-0005 left open.
- **Anonymous visitors see only documents without a plan** (`plan_scope IS NULL`), in the map,
  in search and in `open_documents`. A logged-in customer also sees the documents of their plan.
- **`OLLAMA_NUM_CTX`** (default 16384) is passed to Ollama explicitly, because Ollama truncates
  a prompt longer than its default window without any error.

## Consequences

- A cross-reference question can be answered from a whole document, and the model can choose
  between reading a document and searching, by what the map says each one is for.
- Keyword-only queries now have a path; the evaluation measures how much it helps
  (`backend/evaluation/README.md`, "The knowledge base").
- There is no HNSW or IVFFlat index on `document_chunks.embedding` on purpose: the search is an exact
  scan, which is fast and exact at this size (tens of chunks per tenant). Add one when a single
  tenant's chunks reach the tens of thousands or the search latency shows in traces.
- Every turn pays for the map in prompt tokens; it grows with the number of published
  documents, so a tenant with hundreds of documents will need the map to be filtered or
  searched, which is not built.
- The map is a per-process cache: two API processes can disagree until the next invalidation
  reaches them. Acceptable with one process; a limit before running several.
- `ceil(chars / 3)` overestimates for English and can underestimate for languages with more
  tokens per character. It is a ceiling for the limits, not a measurement.
- A model can still add claims the opened document does not make; the evaluation records it
  (`kb_claim_check` cases) and no guardrail catches it.
- A refund-only question from an anonymous visitor is routed to `billing_question`, which needs
  an identity, so the visitor is asked to identify for what is public policy. Known and left as
  is; recorded as evaluation cases (`kb-gate-001`, `kb-gate-002`).

## Alternatives

- **Pure long context** (every document in every prompt). Simple and exact, but the prompt
  grows with the knowledge base and every turn pays for all of it, on models whose context is
  small and, on Ollama, silently truncated.
- **Redis or a file for the map.** A shared cache would fix the per-process disagreement, but
  adds a service or a file to keep in step for a list that is rebuilt from one query.
- **Exact token counting per provider.** Three providers tokenize differently, and LangChain's
  counter falls back to a GPT-2 tokenizer for Ollama, so the "exact" number would be wrong
  for at least one of them. One estimate everywhere is predictable.
- **Vector search only.** Measured against hybrid in the evaluation.

## References

- Supersedes parts of [ADR-0005](0005-postgres-pgvector-for-rag.md) (re-ingestion that replaces
  chunks, one global document set, no relevance cut) and of
  [ADR-0006](0006-llm-driven-knowledge-base-search.md) (search is the only tool, search returns
  chunks); marked there.
- `backend/app/rag/retriever.py`, `catalog.py`, `tokens.py`
- `backend/app/tools/documents.py`, `backend/app/agent/llm_tools/documents.py`
- `backend/evaluation/kb_dataset.jsonl`, `retrieval_eval.py`
