# AcmeFlow AI Sales & Support Agent

[![CI](https://github.com/TheMutsi/ai-sales-support-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TheMutsi/ai-sales-support-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-oriented AI Sales & Support Agent built for a fictional SaaS product, **AcmeFlow**. It demonstrates agent orchestration with LangGraph, retrieval-augmented generation over a product knowledge base, typed tool calling, a deterministic business-rules layer for upsell decisions, reproducible evaluation, and observability — not a chatbot wrapper around an LLM.

## Why this exists

This project was built to demonstrate AI engineering practice, not to ship an actual product. The scenario (a support agent that also identifies legitimate upsell opportunities) is a stand-in for a common, real constraint in applied AI work: a system whose answers must be grounded in real data, whose business-critical decisions (should this customer be offered an upgrade?) must be deterministic and auditable rather than left to an LLM's judgment, and whose behavior needs to be measurable rather than "looks fine when I try it." The implementation choices throughout — an explicit typed agent state, a separate deterministic business-rules layer, typed tool contracts, a reproducible evaluation suite, and tracing — are there to make those constraints visible and testable, not to inflate the tech stack.

## Status

Under active development. This README will be expanded with the architecture diagrams, evaluation methodology and results, setup instructions, and demo scenarios as the project progresses.

## Documentation

- [Architecture](docs/architecture.md): system and agent-graph diagrams, code layout
- [Architecture decision records](docs/adr/README.md): why each major choice was made, and what it costs
- [Evaluation suite](backend/evaluation/README.md): methodology, results and known limitations

## Stack

- **Backend:** Python 3.12, FastAPI, LangGraph, LangChain (Claude / Gemini / Ollama), PostgreSQL + pgvector
- **Frontend:** Vite + React
- **Observability:** Langfuse (self-hosted)
- **Packaging:** Docker Compose
