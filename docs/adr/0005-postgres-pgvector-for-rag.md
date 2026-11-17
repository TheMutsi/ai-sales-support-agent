# ADR-0005: Postgres + pgvector as the only datastore, with per-doc-type chunking

- **Status:** Accepted
- **Introduced in:** Stage 1 (schema), Stage 3 (RAG pipeline)

## Context

The agent needs relational data (plans, customers, subscriptions, tickets) and
semantic search over a product knowledge base. Retrieval results also need metadata
filters (document type, the plan a document applies to) that are naturally SQL.

## Decision

- **One Postgres with the pgvector extension** holds all application data:
  relational tables and `document_chunks.embedding` (`Vector(768)`). (Langfuse runs
  its own Postgres; that is the tracing stack's storage, not the app's, ADR-0011.) Similarity search is a cosine
  distance query joined to `documents` for metadata.
- **Subscriptions are separate from customers.** A customer's commercial state is a
  history of `subscriptions` rows; the current one is the most recently started.
  Plan changes and cancellations keep their history instead of overwriting a column.
- **Chunking is chosen by document type.** FAQ, policy and billing documents are
  split per `##` section, because a fixed-size cut can separate a question from its
  answer or a rule from its exception. Long prose (features, integrations,
  security) uses fixed-size word windows with overlap. Size is a word count, a
  provider-neutral proxy, since three providers tokenize differently.
- **Re-ingestion is idempotent.** `documents.source` is unique; ingestion replaces a
  document's chunks and commits once at the end, so a failed embedding call leaves
  the previous KB intact.
- **Plan-scoped documents** match their plan or `plan_scope IS NULL` (applies to all
  plans), so general terms are never hidden from a plan-specific query.
- **Metadata comes from YAML front matter**, not from file names or folders: `title` and
  `doc_type` are required (an untagged document is a content bug, so loading raises), values are
  read as text (`version: 1.0` is not a float), and files load in sorted order so every run is the
  same. `documents.source` is the path relative to the KB folder, so the key ingestion replaces on
  is the same on every machine.
- **Section chunking details:** text before the first `##` is its own untitled chunk, and a section
  longer than the limit alone falls back to fixed-size windows. Windows rejoin words with single
  spaces, which loses layout but not meaning, which is what embeddings index.
- **Retrieval selects columns, not entities**, so a top-k result does not carry the 768-dimension
  vector or a document's full text once per matching chunk. `doc_type` and `plan_scope` filter
  before the similarity search, so an off-topic chunk that shares words cannot win.
- **No default `min_score` cutoff.** Cosine search always returns the closest chunks,
  relevant or not; the right cutoff is an empirical question for the evaluation
  suite, not a guess.

## Consequences

- One service to run, back up and migrate; joins between chunks and business data
  are plain SQL.
- pgvector has no SQLite equivalent, so DB and retrieval integration tests need a
  real Postgres (CI runs a `pgvector/pgvector:pg16` service container).
- Section chunking depends on authors using `##` headers consistently; an
  unstructured document silently falls back to fixed-size windows.
- Retrieval quality is not measured directly yet: the evaluation suite sees only the
  HTTP API (see `backend/evaluation/README.md`, known limitations).

## Alternatives

- **A dedicated vector database** (Pinecone, Qdrant, Chroma). A second datastore to
  keep in sync for a knowledge base of a few dozen chunks.
- **One chunking strategy for everything.** Simpler, but the section-vs-window split
  was the reason a question and its answer stay in one chunk.

## References

- `backend/app/db/models.py`, `backend/alembic/`
- `backend/app/rag/chunker.py`, `ingestion.py`, `retriever.py`
