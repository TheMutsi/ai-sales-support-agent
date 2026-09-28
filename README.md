# AcmeFlow AI Sales & Support Agent

[![CI](https://github.com/TheMutsi/ai-sales-support-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TheMutsi/ai-sales-support-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-oriented AI Sales & Support Agent built for a fictional SaaS product, **AcmeFlow**. It demonstrates agent orchestration with LangGraph, retrieval-augmented generation over a product knowledge base, typed tool calling, a deterministic business-rules layer for upsell decisions, reproducible evaluation, and observability — not a chatbot wrapper around an LLM.

## Status

Under active development. This README will be expanded with the architecture diagrams, evaluation methodology and results, setup instructions, and demo scenarios as the project progresses.

## Stack

- **Backend:** Python 3.12, FastAPI, LangGraph, LangChain (Claude / Gemini), PostgreSQL + pgvector
- **Frontend:** Next.js
- **Observability:** LangSmith
- **Packaging:** Docker Compose
