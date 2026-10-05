# ADR-0004: Provider-agnostic chat models and embeddings behind factories

- **Status:** Accepted
- **Introduced in:** Stage 2; `create_chat_model` extracted in PR #46

## Context

The project must run on Anthropic Claude and Google Gemini, and it must also be
developable offline without paying for API calls. Agent nodes, the RAG pipeline and
the evaluation judge all need a model. If each imported a provider SDK, switching
providers would mean editing all of them.

## Decision

- **One factory per capability in `app/core/`.** `get_chat_model()` and
  `get_embeddings()` are the only places that import `ChatAnthropic`,
  `ChatGoogleGenerativeAI`, `ChatOllama` and the embedding classes. Everything else
  depends on LangChain's `BaseChatModel` / `Embeddings` interfaces.
- **Selection is configuration.** `LLM_PROVIDER` (`anthropic` | `google` | `ollama`,
  typed as a `Literal` so a typo fails at startup) and `EMBEDDING_PROVIDER`
  (`google` | `ollama`).
- **Ollama is a first-class provider**, not a test double: `qwen2.5:7b-instruct` for
  the agent and `nomic-embed-text` for embeddings, no API key needed.
- **Both embedding models output 768 dimensions**, matching `EMBEDDING_DIM` in the
  `document_chunks.embedding` column, so switching providers needs a re-ingest but no
  migration.
- **`create_chat_model(provider, model)`** builds an explicit pair for callers that
  must not use the configured model, such as the evaluation judge (ADR-0012).
- LangChain is used for this abstraction (and for tool binding and structured
  output), not as a general framework.

## Consequences

- Provider choice is an environment change, never a code change.
- Behavior is not provider-agnostic, only the code is. All evaluation numbers so far
  come from a 7B local model; a different provider needs its own evaluation run, and
  calibrated values such as the safety threshold (ADR-0007) must be re-checked.
- Embeddings from different providers are not comparable: switching
  `EMBEDDING_PROVIDER` requires re-running ingestion.
- `get_chat_model()` is cached per process, so a provider change needs a restart.

## Alternatives

- **One provider SDK used directly.** Simpler, but no offline development and no
  way to compare models.
- **OpenAI**: deliberately not a dependency of this project.
- **A routing proxy (e.g. LiteLLM).** Another service to run for what three `if`
  branches already do.

## References

- `backend/app/core/llm.py`, `backend/app/core/embeddings.py`, `backend/app/core/config.py`
- `backend/app/db/models.py` (`EMBEDDING_DIM`)
