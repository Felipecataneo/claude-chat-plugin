#!/usr/bin/env python3
"""
context_chat.py — Backend de chat Q&A sobre contexto curado.

Plugin único de arquivo. Sobe um endpoint SSE que responde perguntas
usando um de dois provedores:

  - "cli"  -> chama o Claude Code CLI já autenticado na máquina (custo zero,
              só local, não faz deploy decente).
  - "api"  -> chama a Anthropic Messages API com streaming real (precisa de
              ANTHROPIC_API_KEY, mas faz deploy, escala e é seguro expor).

Rodar standalone:
    pip install -r requirements.txt
    python context_chat.py            # usa chat_config.json ao lado

Montar dentro de um app FastAPI existente:
    from context_chat import build_router
    app.include_router(build_router("chat_config.json"))

Config: chat_config.json (ver exemplo no repositório).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_GUARDRAILS = [
    "Responda apenas com base no contexto fornecido e nos arquivos autorizados.",
    "Nunca exponha codigo-fonte (.py .jsx .js .ts .sql .env) nem segredos.",
    "Nunca invente numeros, nomes de clientes ou dados internos.",
    "Se nao tiver certeza, diga 'Isso precisaria de analise adicional'.",
    "Respostas concisas (3-6 linhas).",
    "Portugues brasileiro, tom tecnico mas acessivel.",
]


class Config(BaseModel):
    provider: str = "cli"                      # "cli" | "api"
    presentation_name: str = ""
    context_file: str = "context.md"
    allow_file_fallback: bool = False
    fallback_files: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    # api provider
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024
    # operacional
    request_timeout_s: int = 120
    max_history_turns: int = 8                 # pares user/assistant mantidos
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    auth_token: str = ""                       # se setado, exige Bearer no header
    root: str = "."                            # raiz para resolver caminhos


def load_config(path: str | Path) -> Config:
    p = Path(path)
    data: dict[str, Any] = {}
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        print(f"[context_chat] AVISO: {p} nao encontrado, usando defaults.", file=sys.stderr)
    cfg = Config(**data)
    # raiz default = diretorio do config
    if cfg.root == ".":
        cfg.root = str(p.resolve().parent if p.exists() else Path.cwd())
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Contexto: carrega uma vez, cacheia, reload manual via /reload
# ─────────────────────────────────────────────────────────────────────────────

class ContextStore:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._context = ""
        self.reload()

    def reload(self) -> None:
        root = Path(self.cfg.root)
        ctx_path = root / self.cfg.context_file
        if ctx_path.exists():
            self._context = ctx_path.read_text(encoding="utf-8")
        else:
            self._context = ""
            print(f"[context_chat] AVISO: contexto {ctx_path} nao encontrado.", file=sys.stderr)

    @property
    def context(self) -> str:
        return self._context

    def system_prompt(self) -> str:
        guardrails = DEFAULT_GUARDRAILS + list(self.cfg.guardrails)
        rules = "\n".join(f"- {g}" for g in guardrails)
        name = self.cfg.presentation_name or "esta aplicacao"
        return (
            f"Voce e um assistente de Q&A sobre: {name}.\n"
            f"Regras:\n{rules}\n\n"
            f"=== CONTEXTO ===\n{self._context}\n=== FIM DO CONTEXTO ==="
        )


# ─────────────────────────────────────────────────────────────────────────────
# Provedores de streaming. Cada um e um async generator de tokens (str).
# ─────────────────────────────────────────────────────────────────────────────

def _trim_history(history: list[dict], max_turns: int) -> list[dict]:
    # mantem os ultimos max_turns*2 itens, normaliza papeis
    clean = [
        {"role": h.get("role"), "content": str(h.get("content", ""))}
        for h in history
        if h.get("role") in ("user", "assistant") and h.get("content")
    ]
    return clean[-max_turns * 2 :]


async def _stream_cli(
    cfg: Config, system: str, message: str, history: list[dict]
) -> AsyncIterator[str]:
    """Chama o Claude Code CLI. Prompt vai por stdin. Streaming best-effort."""
    binary = shutil.which("claude")
    if not binary:
        raise RuntimeError("CLI 'claude' nao encontrado no PATH.")

    # Monta o prompt completo: system + historico + pergunta atual.
    convo = "\n".join(f"{h['role'].upper()}: {h['content']}" for h in history)
    full_prompt = f"{system}\n\n{convo}\n\nUSER: {message}\nASSISTANT:".strip()

    args = [binary, "-p", "--output-format", "text"]
    if cfg.allow_file_fallback and cfg.fallback_files:
        args += ["--allowedTools", "Read"]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cfg.root,
    )

    assert proc.stdin and proc.stdout
    proc.stdin.write(full_prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    async def pump() -> AsyncIterator[str]:
        while True:
            chunk = await proc.stdout.read(256)
            if not chunk:
                break
            yield chunk.decode("utf-8", errors="replace")

    try:
        async for token in _with_timeout(pump(), cfg.request_timeout_s):
            yield token
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        if proc.returncode not in (0, None):
            err = (await proc.stderr.read()).decode("utf-8", errors="replace")
            if err.strip():
                raise RuntimeError(f"CLI saiu com erro: {err.strip()[:300]}")


async def _stream_api(
    cfg: Config, system: str, message: str, history: list[dict]
) -> AsyncIterator[str]:
    """Chama a Anthropic Messages API com streaming SSE real."""
    try:
        from anthropic import AsyncAnthropic
    except ImportError as e:
        raise RuntimeError("Pacote 'anthropic' nao instalado (pip install anthropic).") from e

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY nao definida no ambiente.")

    client = AsyncAnthropic()
    messages = history + [{"role": "user", "content": message}]

    async def gen() -> AsyncIterator[str]:
        async with client.messages.stream(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async for token in _with_timeout(gen(), cfg.request_timeout_s):
        yield token


async def _with_timeout(agen: AsyncIterator[str], timeout_s: int) -> AsyncIterator[str]:
    """Aplica timeout por-token. Se um token demora demais, aborta."""
    ait = agen.__aiter__()
    while True:
        try:
            token = await asyncio.wait_for(ait.__anext__(), timeout=timeout_s)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as e:
            raise RuntimeError(f"Timeout apos {timeout_s}s sem resposta.") from e
        yield token


PROVIDERS = {"cli": _stream_cli, "api": _stream_api}


# ─────────────────────────────────────────────────────────────────────────────
# Router FastAPI
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)


def build_router(config_path: str | Path = "chat_config.json", prefix: str = "/api/v1") -> APIRouter:
    cfg = load_config(config_path)
    store = ContextStore(cfg)
    router = APIRouter(prefix=prefix)

    def _check_auth(authorization: str | None) -> None:
        if cfg.auth_token:
            expected = f"Bearer {cfg.auth_token}"
            if authorization != expected:
                raise HTTPException(status_code=401, detail="Nao autorizado.")

    @router.get("/presentation/health")
    async def health() -> dict:
        return {
            "ok": True,
            "provider": cfg.provider,
            "context_chars": len(store.context),
            "presentation": cfg.presentation_name,
        }

    @router.post("/presentation/reload")
    async def reload_ctx(authorization: str | None = Header(default=None)) -> dict:
        _check_auth(authorization)
        store.reload()
        return {"ok": True, "context_chars": len(store.context)}

    @router.post("/presentation/chat")
    async def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
        _check_auth(authorization)
        if cfg.provider not in PROVIDERS:
            raise HTTPException(500, f"Provider invalido: {cfg.provider}")
        if not req.message.strip():
            raise HTTPException(400, "Mensagem vazia.")

        provider = PROVIDERS[cfg.provider]
        system = store.system_prompt()
        history = _trim_history(req.history, cfg.max_history_turns)

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                async for token in provider(cfg, system, req.message, history):
                    if token:
                        payload = json.dumps({"text": token}, ensure_ascii=False)
                        yield f"data: {payload}\n\n".encode("utf-8")
            except Exception as e:  # noqa: BLE001 — superficie controlada ao cliente
                payload = json.dumps({"error": str(e)}, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")
            finally:
                yield b"data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def build_app(config_path: str | Path = "chat_config.json") -> FastAPI:
    cfg = load_config(config_path)
    app = FastAPI(title="Context Chat Plugin")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_router(config_path))
    return app


if __name__ == "__main__":
    import uvicorn

    cfg_path = os.getenv("CHAT_CONFIG", "chat_config.json")
    app = build_app(cfg_path)
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
