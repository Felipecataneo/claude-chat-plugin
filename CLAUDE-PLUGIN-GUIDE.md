# context-chat — Guia de Integração para Claude

Este arquivo instrui o Claude Code sobre o plugin context-chat e como integrá-lo
a um repositório de apresentação.

---

## O que é o plugin

`context-chat` é um widget de Q&A que se anexa a qualquer apresentação web.
Ele abre um chat flutuante (canto inferior direito) que responde perguntas
usando o Claude, com base em um `context.md` gerado dos próprios docs da
apresentação. Oculto automaticamente em export PDF.

**Não é RAG**: o contexto inteiro é injetado no prompt (context-stuffing).
Funciona bem até ~150 KB de texto relevante.

## Onde fica o plugin

```
/home/felipe/Documentos/repositorios/context-chat-plugin/
├── backend/
│   ├── context_chat.py     # FastAPI: SSE, dois providers (cli / api)
│   ├── requirements.txt
│   └── chat_config.json    # configuração do backend
├── frontend/
│   ├── context-chat.js     # Web Component <context-chat> (zero deps, drop-in)
│   └── ContextChat.jsx     # wrapper React opcional
├── generate_context.py     # gera context.md a partir dos docs
└── gen_sources.json        # quais arquivos entram no context.md
```

## Como integrar nesta apresentação

### Passo 1 — Identificar os docs a incluir no contexto

Pergunte ao usuário (ou infira dos arquivos) quais documentos descrevem o
conteúdo da apresentação. Exemplos: `README.md`, `docs/*.md`, `slides/*.md`.

Crie ou edite `/home/felipe/Documentos/repositorios/context-chat-plugin/gen_sources.json`:

```json
{
  "sources": {
    "caminho/relativo/ao/plugin/ou/glob": null,
    "outro/arquivo.md": ["## Seção específica"]
  },
  "max_chars_per_section": 4000,
  "max_chars_full_file": 8000,
  "budget_kb": 40
}
```

`null` = arquivo inteiro. Lista de strings = apenas essas seções (pelo heading exato).
Os caminhos são relativos à raiz do plugin (`/home/felipe/Documentos/repositorios/context-chat-plugin/`).
Para apontar para arquivos desta apresentação, use caminhos absolutos ou relativos corretos.

### Passo 2 — Gerar o context.md

```bash
cd /home/felipe/Documentos/repositorios/context-chat-plugin
python generate_context.py
```

Revise o `context.md` gerado. Remova informações sensíveis antes de usar.

### Passo 3 — Configurar o backend

Edite `/home/felipe/Documentos/repositorios/context-chat-plugin/backend/chat_config.json`:

```json
{
  "provider": "cli",
  "presentation_name": "Nome da Apresentação",
  "context_file": "context.md",
  "root": "..",
  "guardrails": [],
  "request_timeout_s": 120,
  "max_history_turns": 8,
  "cors_origins": ["*"],
  "auth_token": ""
}
```

Campos que normalmente mudam por apresentação:
- `"presentation_name"` — aparece no header do chat
- `"guardrails"` — regras adicionais somadas às padrão (ex: `"Cite apenas dados do contexto."`)
- `"provider"` — `"cli"` usa o `claude` já autenticado (grátis, só local); `"api"` usa `ANTHROPIC_API_KEY`

### Passo 4 — Subir o backend

```bash
cd /home/felipe/Documentos/repositorios/context-chat-plugin/backend
uv run python context_chat.py
```

Backend sobe em `http://localhost:8000`. Verificar:
```bash
curl http://localhost:8000/api/v1/presentation/health
# deve retornar {"ok":true,"provider":"cli","context_chars":<número>,...}
```

Se `context_chars` for 0 ou pequeno demais, o context.md não foi gerado ou o
caminho `root` está errado no `chat_config.json`.

### Passo 5 — Adicionar o widget à apresentação

Copie `context-chat.js` para dentro do repositório da apresentação (ou sirva
diretamente do plugin). Adicione antes de `</body>`:

**HTML puro / Reveal.js / Marp / Slidev:**
```html
<script src="caminho/para/context-chat.js"></script>
<context-chat
  endpoint="http://localhost:8000/api/v1/presentation/chat"
  title="Q&A com IA">
</context-chat>
```

**React / Next.js:**
```jsx
// Copie context-chat.js para /public e ContextChat.jsx para /src/components
import ContextChat from "./components/ContextChat";
// use no último slide ou em qualquer lugar:
<ContextChat endpoint="http://localhost:8000/api/v1/presentation/chat" />
```

**Vue / Svelte / Angular** — Web Component nativo:
```html
<context-chat endpoint="http://localhost:8000/api/v1/presentation/chat"></context-chat>
```

## Atributos do widget

| Atributo | Descrição |
|---|---|
| `endpoint` | URL do backend (obrigatório) |
| `title` | Texto no botão e header (padrão: "Q&A com IA") |
| `auth` | Bearer token se `auth_token` estiver configurado |
| `fullscreen` | Abre direto em tela cheia (para plateia ver projetado) |

## Endpoints úteis durante apresentação

```bash
# Checar saúde e tamanho do contexto
GET  http://localhost:8000/api/v1/presentation/health

# Recarregar context.md sem reiniciar o backend
POST http://localhost:8000/api/v1/presentation/reload
```

## Troubleshooting rápido

**"CLI 'claude' nao encontrado"** — o `claude` não está no PATH do processo.
Verifique: `which claude`. Se necessário: `export PATH="$HOME/.local/bin:$PATH"`.

**Resposta não aparece / erro CORS** — teste direto:
```bash
curl -N -X POST http://localhost:8000/api/v1/presentation/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"teste","history":[]}'
```
Deve retornar linhas `data: ...` terminando em `data: [DONE]`.

**context_chars: 0 no health** — o `context.md` está vazio ou o path `root`
em `chat_config.json` está errado. `root: ".."` é o valor correto quando o
backend roda de dentro de `backend/`.

**Chat aparece no PDF** — o Web Component já tem `@media print { display:none }`
no Shadow DOM. Se usou outro markup, adicione a regra manualmente.
