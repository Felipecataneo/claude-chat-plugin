# context-chat — plugin de Q&A sobre contexto para qualquer web app

Adiciona um chat que responde perguntas usando **apenas** um contexto curado
(`context.md`) que você gera dos seus docs. Pensado para apresentar POCs como
sites em vez de slides, com Q&A ao vivo. Oculto automaticamente no export PDF.

Não é RAG por embeddings: é **context-stuffing** (injeta o contexto no prompt).
Para apresentação isso é melhor — mais simples e sem índice. Só vire para
retrieval de verdade se seus docs passarem do tamanho de contexto do modelo
(na prática, > ~150 KB de texto relevante).

## Dois backends — escolha pelo `provider` no `chat_config.json`

| | `cli` | `api` |
|---|---|---|
| Custo | zero (usa seu Claude Code já autenticado) | cobra na API |
| Onde roda | só sua máquina local | deploy em servidor, escala |
| Expor publicamente | **não** (risco de leitura de arquivo) | sim |
| Streaming | best-effort | token a token real |
| Requisito | `claude` no PATH | `ANTHROPIC_API_KEY` |

Use `cli` para apresentar você mesmo no localhost. Use `api` quando a POC
precisar ficar de pé num servidor ou acessível a outras pessoas.

## Arquivos

```
context-chat-plugin/
├── backend/
│   ├── context_chat.py     # FastAPI: endpoint SSE, dois providers, timeout, auth
│   ├── requirements.txt
│   └── chat_config.json    # provider, guardrails, fallback, auth
├── generate_context.py     # gera context.md dos seus docs (globs, orçamento)
├── gen_sources.json        # quais docs entram no contexto
├── context.md              # contexto curado (gerado)
└── frontend/
    ├── context-chat.js     # Web Component <context-chat> (qualquer framework)
    └── ContextChat.jsx     # wrapper React opcional
```

## Instalação

### 1. Backend

```bash
cd backend
pip install -r requirements.txt          # 'anthropic' só é usado no provider api
```

Para `provider: "cli"`, confirme o CLI:
```bash
which claude
claude -p "oi" --output-format text
```

Para `provider: "api"`:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Gere o contexto

Edite `gen_sources.json` apontando para seus docs (aceita globs), depois:
```bash
python generate_context.py               # gera context.md
python generate_context.py --budget-kb 30
```
Revise o `context.md` e remova qualquer coisa sensível — ele vai para o modelo.

### 3. Suba o backend

Standalone:
```bash
cd backend
python context_chat.py                   # porta 8000, lê chat_config.json
```

Ou monte no seu app FastAPI existente:
```python
from context_chat import build_router
app.include_router(build_router("chat_config.json"))
```

### 4. Adicione o widget no frontend

**HTML puro / Reveal.js / Slidev / Marp** — cole no fim do `<body>` (ou na
última `<section>`):
```html
<script src="context-chat.js"></script>
<context-chat endpoint="http://localhost:8000/api/v1/presentation/chat"
              title="Q&A com IA"></context-chat>
```

**React / Vite** — copie `context-chat.js` para `/public`, depois:
```jsx
import ContextChat from "./ContextChat";
{isLastSlide && <ContextChat endpoint="http://localhost:8000/api/v1/presentation/chat" />}
```

**Next.js** — igual ao React, mas adicione `"use client"` no topo de `ContextChat.jsx`.

**Vue / Svelte / Angular** — Web Component nativo, só use a tag direto:
```html
<context-chat endpoint="http://localhost:8000/api/v1/presentation/chat"></context-chat>
```

## Configuração — `chat_config.json`

| Campo | Padrão | Descrição |
|---|---|---|
| `provider` | `"cli"` | `"cli"` ou `"api"` |
| `presentation_name` | `""` | nome no header do chat |
| `context_file` | `"context.md"` | arquivo de contexto curado |
| `allow_file_fallback` | `false` | só `cli`: deixa o Claude usar `Read` nos `fallback_files` |
| `fallback_files` | `[]` | caminhos que o modelo pode ler se o contexto não bastar |
| `guardrails` | `[]` | regras **somadas** às padrão (não substituem) |
| `model` | `"claude-sonnet-4-6"` | só `api` |
| `max_tokens` | `1024` | só `api` |
| `request_timeout_s` | `120` | aborta se travar |
| `max_history_turns` | `8` | pares user/assistant mantidos |
| `cors_origins` | `["*"]` | restrinja em produção |
| `auth_token` | `""` | se setado, exige `Authorization: Bearer <token>` |
| `root` | `"."` | raiz para resolver caminhos relativos |

## Segurança — leia antes de expor

- `provider: "cli"` com `allow_file_fallback: true` permite o modelo ler
  arquivos do projeto. **Nunca** exponha esse modo na internet.
- Para qualquer acesso além do seu localhost: use `provider: "api"`, defina
  `auth_token`, restrinja `cors_origins` e ponha atrás de HTTPS.
- O `context.md` vai inteiro para o modelo. Não coloque segredo nele.

## Endpoints

- `POST /api/v1/presentation/chat` — `{message, history}` → stream SSE
- `GET  /api/v1/presentation/health` — status e tamanho do contexto
- `POST /api/v1/presentation/reload` — recarrega `context.md` sem reiniciar
  (respeita `auth_token`)

## Troubleshooting

**"CLI 'claude' nao encontrado"** — `claude` não está no PATH do processo do
backend. `echo $PATH`; se via npm: `export PATH="$HOME/.npm-global/bin:$PATH"`.

**Resposta não aparece** — teste direto:
```bash
curl -N -X POST http://localhost:8000/api/v1/presentation/chat \
  -H "Content-Type: application/json" -d '{"message":"teste","history":[]}'
```
Deve sair linhas `data: ...` terminando em `data: [DONE]`.

**Contexto desatualizado** — `POST /api/v1/presentation/reload` ou reinicie.

**Chat aparece no PDF** — o Web Component já tem `@media print` no Shadow DOM.
Se você usou outro markup, garanta a regra `@media print { ... display:none }`.
