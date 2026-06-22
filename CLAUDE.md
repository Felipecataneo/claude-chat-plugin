# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Integrando em uma apresentação

Para integrar o plugin em outro repositório, leia `CLAUDE-PLUGIN-GUIDE.md`.
Esse arquivo contém o passo a passo completo que o Claude deve seguir para
configurar o contexto, o backend e adicionar o widget ao HTML da apresentação.

## Commands

```bash
# Install backend dependencies
cd backend && pip install -r requirements.txt

# Generate context.md from configured sources
python generate_context.py
python generate_context.py --budget-kb 30

# Run backend (port 8000, reads backend/chat_config.json)
cd backend && python context_chat.py

# Test the chat endpoint
curl -N -X POST http://localhost:8000/api/v1/presentation/chat \
  -H "Content-Type: application/json" -d '{"message":"teste","history":[]}'

# Check health / context size
curl http://localhost:8000/api/v1/presentation/health

# Reload context.md without restarting
curl -X POST http://localhost:8000/api/v1/presentation/reload
```

## Architecture

**Single-purpose plugin** for adding a Q&A chat widget to any web presentation. Uses context-stuffing (full `context.md` injected into system prompt), not RAG/embeddings.

### Backend (`backend/context_chat.py`)

Single-file FastAPI app with two provider strategies, selectable via `chat_config.json`:

- **`cli` provider** — calls the `claude` CLI binary via subprocess, reading stdout as streaming text. Prompt is assembled as a flat string (system + history turns + user message). Only viable locally.
- **`api` provider** — calls the Anthropic Messages API with true SSE streaming. Requires `ANTHROPIC_API_KEY`.

Key components:
- `Config` (Pydantic model) — all runtime settings loaded from `chat_config.json`
- `ContextStore` — loads and caches `context.md`; `system_prompt()` assembles the final system string from default guardrails + custom guardrails + context text
- `_trim_history()` — keeps the last `max_history_turns * 2` messages before each request
- `_with_timeout()` — per-token timeout wrapper for both async generators
- `build_router()` — the primary entry point; can be mounted into an existing FastAPI app
- SSE format: `data: {"text": "..."}` lines, terminated by `data: [DONE]`

### Frontend (`frontend/context-chat.js`)

Zero-dependency Web Component (`<context-chat>`). All styles are encapsulated in Shadow DOM, including `@media print { display: none }` to hide during PDF export. Two display modes: corner popover and fullscreen (for projecting to an audience). `ContextChat.jsx` is a thin React wrapper that loads the Web Component.

### Context generation (`generate_context.py`)

Reads `gen_sources.json` to know which files/globs to include and their section filters. Enforces a KB budget and truncates gracefully. Output is `context.md`.

### Configuration

- `backend/chat_config.json` — runtime config for the backend (provider, guardrails, model, auth, CORS, etc.)
- `gen_sources.json` — which source files feed into `context.md`, with optional heading filters and size limits

### Mounting as a plugin (not standalone)

```python
from context_chat import build_router
app.include_router(build_router("path/to/chat_config.json"))
```

The `root` field in `chat_config.json` controls where relative paths (context file, fallback files) are resolved from.
