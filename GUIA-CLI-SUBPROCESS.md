# Guia: rodar o Claude Code via subprocess do CLI (sem API key)

Este guia documenta a técnica usada no provider `cli` de
`backend/context_chat.py` para chamar o Claude **programaticamente** sem usar
`ANTHROPIC_API_KEY` e sem depender do Agent SDK. Serve de receita para
replicar em qualquer outro código (Python, Node, Go, shell — o princípio é o
mesmo).

---

## 1. A ideia em uma frase

Em vez de falar com a Anthropic Messages API (que cobra **tokens de API**
pré-pagos via `ANTHROPIC_API_KEY`), você **spawna o binário `claude` que já
está logado na máquina** e lê a resposta dele pela stdout. Como o CLI usa as
credenciais da sua **sessão logada** (plano Pro/Max), o consumo sai pelo
**plano**, não pela cota de API.

```
seu código  ──spawn──▶  claude -p "<prompt>"  ──▶  API da Anthropic
                         (usa o login do CLI)      (créditos do plano)
```

---

## 2. Sobre a frase "isso contorna a limitação da SDK" (honestidade técnica)

Vale separar o que é mito do que é real:

- **Real:** chamando o binário `claude` diretamente, você usa a autenticação
  já existente do CLI. Se esse CLI está logado com um plano (Pro/Max), o uso é
  faturado pelo plano e você **não precisa** de `ANTHROPIC_API_KEY`.
- **Nuance:** o **Agent SDK oficial também spawna o mesmo CLI** por baixo e
  também consegue usar a credencial do plano. Ou seja, o ganho aqui **não é**
  "burlar a SDK" — é **eliminar a dependência da SDK** e ter controle total do
  subprocess, com zero pacotes extras. A SDK adiciona protocolo estruturado,
  sessões e tipagem; este método troca tudo isso por simplicidade.

**Resumo honesto:** você troca os recursos da SDK por um subprocess cru. O
faturamento pelo plano vem do **CLI logado**, não de algum truque.

---

## 3. Pré-requisitos

1. **Claude Code CLI instalado e logado** na máquina/container onde o backend
   roda:
   ```bash
   npm install -g @anthropic-ai/claude-code   # ou o instalador oficial
   claude            # rode uma vez e faça login interativo (escolha o plano)
   claude -p "ping"  # confirme que responde sem pedir API key
   ```
2. O processo do seu backend precisa enxergar o **mesmo `$HOME`/credenciais**
   do usuário que fez login (cuidado com systemd/containers que mudam o HOME).
3. `claude` precisa estar no `PATH` do processo do backend.

> ⚠️ **Limitações reais deste método**
> - Só funciona onde dá pra logar o CLI (máquina sua / VM / container com login
>   persistido). **Não escala** em serverless stateless nem em deploy multi-réplica.
> - O streaming é *best-effort*: você lê stdout em chunks, não eventos tipados.
> - Está sujeito aos **rate limits do plano**, não aos da API.

---

## 4. A receita mínima (Python, asyncio)

O coração da técnica são ~30 linhas. Esta é a versão essencial do que está em
`backend/context_chat.py` (`_stream_cli`):

```python
import asyncio
import shutil
from typing import AsyncIterator


async def stream_claude_cli(prompt: str, cwd: str = ".") -> AsyncIterator[str]:
    # 1. Localiza o binário logado
    binary = shutil.which("claude")
    if not binary:
        raise RuntimeError("CLI 'claude' nao encontrado no PATH.")

    # 2. Modo headless: -p (print) + saida em texto puro
    args = [binary, "-p", "--output-format", "text"]

    # 3. Spawn como subprocess, prompt vai por STDIN (evita limite de argv)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    proc.stdin.write(prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    # 4. Le stdout em chunks -> streaming best-effort
    try:
        while True:
            chunk = await proc.stdout.read(256)
            if not chunk:
                break
            yield chunk.decode("utf-8", errors="replace")
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        if proc.returncode not in (0, None):
            err = (await proc.stderr.read()).decode("utf-8", errors="replace")
            if err.strip():
                raise RuntimeError(f"CLI saiu com erro: {err.strip()[:300]}")
```

Uso:

```python
async def main():
    async for token in stream_claude_cli("Explique o que é entropia em 2 linhas."):
        print(token, end="", flush=True)

asyncio.run(main())
```

---

## 5. Pontos de implementação que importam

| Decisão | Por quê |
|---|---|
| `-p` / `--print` | Modo **headless/não-interativo**: o CLI lê o prompt, responde e sai. Sem isso ele abre a UI interativa e trava seu backend. |
| `--output-format text` | Devolve texto cru. Para parsing estruturado existe `--output-format stream-json` (cada linha é um evento JSON). |
| Prompt por **stdin** | Prompts grandes (system + contexto + histórico) estouram o limite de tamanho de argumento (`argv`). Stdin não tem esse limite. |
| `create_subprocess_exec` (lista de args) | Nunca use `shell=True` / string concatenada: evita injeção de shell quando o prompt vem do usuário. |
| Ler em chunks (256 bytes) | Dá efeito de streaming. O CLI não emite SSE; você fatia o stdout. |
| `proc.kill()` no `finally` | Se o cliente desconectar ou der timeout, você não deixa processo `claude` zumbi. |
| Checar `returncode` + stderr | O CLI sinaliza erro (ex.: não-logado, rate limit) pelo exit code e stderr. |

---

## 6. Montando o prompt completo (system + histórico)

O CLI headless não tem conceito nativo de "system prompt" + "mensagens" como a
API. A solução é **achatar tudo numa string só** antes de mandar pro stdin:

```python
def build_prompt(system: str, history: list[dict], message: str) -> str:
    convo = "\n".join(f"{h['role'].upper()}: {h['content']}" for h in history)
    return f"{system}\n\n{convo}\n\nUSER: {message}\nASSISTANT:".strip()
```

> Para system prompt "de verdade", o CLI aceita `--system-prompt` /
> `--append-system-prompt`. Mas para o caso de context-stuffing, achatar tudo
> num bloco único funciona bem e é mais portável entre versões do CLI.

---

## 7. Liberando ferramentas (Read, etc.)

Se quiser que o Claude possa **ler arquivos** durante a resposta (RAG simples
em cima do filesystem), libere as tools explicitamente — caso contrário o CLI
roda em modo restrito:

```python
args = [binary, "-p", "--output-format", "text", "--allowedTools", "Read"]
```

Combine com `cwd=` apontando pra raiz dos arquivos permitidos. **Cuidado:**
liberar tools dá ao modelo acesso ao filesystem do processo — restrinja o `cwd`
e a allowlist ao mínimo.

---

## 8. Isolamento de contexto (igualar a "API crua")

**O problema:** o `claude` CLI, por padrão, injeta contexto que uma chamada de
API crua (Qwen, OpenAI, Anthropic Messages API) **não teria**: o `CLAUDE.md`
do repo via auto-discovery, `settings.json`, hooks, servidores MCP, agents,
output styles, além de seções dinâmicas no system prompt (cwd, env, git
status, identidade de "Claude Code"). Se você quer que o modelo receba
**exatamente o mesmo que receberia via API crua — só o seu prompt** — precisa
desligar tudo isso.

**A solução são três camadas, todas verificadas contra o CLI v2.1.x:**

```python
args = [
    binary,
    "-p", "--output-format", "text",
    "--safe-mode",                       # camada 1
    "--tools", "",                       # camada 2
    "--system-prompt", neutral_prompt,   # camada 3
]
proc = await asyncio.create_subprocess_exec(*args, ..., cwd=empty_tmp_dir)
```

### Camada 1 — `--safe-mode` (desliga customizações, MANTÉM o login do plano)

Do `--help`:
> *"Start with all customizations (CLAUDE.md, skills, plugins, hooks, MCP
> servers, custom commands and agents, output styles, ...) disabled. **Auth,
> model selection, built-in tools, and permissions work normally.** Sets
> `CLAUDE_CODE_SAFE_MODE=1`."*

É exatamente o que queremos: zero auto-discovery de `CLAUDE.md`/settings/hooks/
MCP/agents, **e o login OAuth do plano continua funcionando**.

> ⚠️ **Não confunda com `--bare`.** O `--bare` também desliga o auto-discovery,
> **mas força a autenticação a ser `ANTHROPIC_API_KEY`/`apiKeyHelper` — "OAuth
> and keychain are never read"**. Ou seja, `--bare` **quebra o login do plano**
> e te joga de volta na cota de API paga. Para isolar mantendo o plano, é
> `--safe-mode`, nunca `--bare`.
>
> ⚠️ **Ressalva:** o `--safe-mode` diz *"Admin-managed (policy) settings still
> apply"*. Em máquina pessoal não há política gerenciada; em ambiente
> corporativo com managed settings, essas ainda carregam.

### Camada 2 — `--tools ""` (zero acesso ao filesystem)

Do `--help`:
> *"Specify the list of available tools from the built-in set. Use `""` to
> disable all tools, `"default"` to use all tools, or specify tool names."*

`--safe-mode` mantém as built-in tools "work normally", então **é o `--tools
""` que tira o acesso ao disco**. Sem isso o modelo poderia ler arquivos do
`cwd` (verifier.py, definições de problema, etc.). As duas flags são
complementares, não redundantes.

### Camada 3 — system prompt neutro + cwd temporário vazio

- **Use `--system-prompt`, NÃO `--append-system-prompt`.** O `--append-...`
  apenas *adiciona* ao prompt default do Claude Code (que traz identidade de
  agente + seções dinâmicas). O `--system-prompt` **substitui** o default
  inteiro. Bônus confirmado no `--help`: `--exclude-dynamic-system-prompt-sections`
  é "ignored with `--system-prompt`" — ou seja, ao passar `--system-prompt`, as
  seções de `cwd`/env/git status **já não entram**.
- **`cwd` = diretório temporário vazio.** Defesa em profundidade: mesmo que algo
  tente auto-discovery, não há `CLAUDE.md` nem arquivos para encontrar.

```python
import tempfile

with tempfile.TemporaryDirectory() as empty:
    proc = await asyncio.create_subprocess_exec(
        binary, "-p", "--output-format", "text",
        "--safe-mode", "--tools", "", "--system-prompt", "Voce e um assistente util.",
        stdin=PIPE, stdout=PIPE, stderr=PIPE,
        cwd=empty,
    )
```

### Tornando isso um toggle (`CLAUDE_CLI_ISOLATED`)

Vale expor como flag de config do *seu* app (não é flag do CLI), default ligado:

```python
def cli_args(binary: str, isolated: bool, system: str) -> list[str]:
    args = [binary, "-p", "--output-format", "text"]
    if isolated:
        args += ["--safe-mode", "--tools", "", "--system-prompt", system]
    return args
```

Resultado com `isolated=True`: o agente recebe **o mesmo contexto que um
Qwen/OpenAI receberia — só o prompt** — mas faturado pelo plano via OAuth.

---

## 9. Timeout por token (resiliência)

Para não pendurar a requisição se o CLI travar, envolva o generator num
wrapper de timeout por chunk:

```python
async def with_timeout(agen, timeout_s: int):
    ait = agen.__aiter__()
    while True:
        try:
            token = await asyncio.wait_for(ait.__anext__(), timeout=timeout_s)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as e:
            raise RuntimeError(f"Timeout apos {timeout_s}s sem resposta.") from e
        yield token
```

---

## 10. Equivalente em Node.js (mesma técnica)

```js
import { spawn } from "node:child_process";

function streamClaudeCli(prompt, { cwd = "." } = {}) {
  const proc = spawn("claude", ["-p", "--output-format", "text"], { cwd });
  proc.stdin.write(prompt);
  proc.stdin.end();
  proc.stdout.setEncoding("utf-8");
  return proc.stdout; // async iterable de chunks
}

const out = streamClaudeCli("Resuma a teoria da relatividade em 2 linhas.");
for await (const chunk of out) process.stdout.write(chunk);
```

A flag `--print`/`-p` e o input por stdin são idênticos; muda só a API de
processo da linguagem.

---

## 11. Quando NÃO usar isto

Escolha o provider `api` (Anthropic Messages API com `ANTHROPIC_API_KEY`) quando:

- For fazer **deploy real** (serverless, várias réplicas, autoscaling);
- Precisar de **streaming SSE confiável** e eventos estruturados;
- Não puder garantir um CLI logado no ambiente de execução;
- Precisar de **SLA/segurança** de produção (chave gerenciada por secret).

Use o provider `cli` (esta técnica) para: **demos locais, protótipos, uso
interno numa máquina sua**, onde "custo zero" pelo plano > robustez.

---

## 12. Checklist de replicação

- [ ] `claude` instalado e `claude -p "ping"` responde sem pedir API key
- [ ] Binário no `PATH` do processo do backend
- [ ] Spawn com `-p --output-format text` e prompt via **stdin**
- [ ] Sem `shell=True`; args como lista
- [ ] Leitura de stdout em chunks para streaming
- [ ] `kill()` + `wait()` no finally; checagem de `returncode`/stderr
- [ ] Timeout por token
- [ ] (Opcional) `--allowedTools` + `cwd` restrito se precisar de file access
- [ ] **Isolamento:** `--safe-mode` + `--tools ""` + `--system-prompt` + cwd temp vazio
- [ ] Conferir que NÃO usou `--bare` (quebraria o login do plano)
- [ ] Plano B `api` documentado para produção
```
