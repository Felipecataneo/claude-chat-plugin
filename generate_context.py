#!/usr/bin/env python3
"""
generate_context.py — Constroi context.md (contexto curado) a partir de docs.

Diferente da versao anterior, este gerador:
  - aceita globs ("docs/*.md") alem de caminhos diretos;
  - tem orcamento global de tamanho (corta antes de estourar o contexto);
  - extracao de secao por heading robusta (funciona em fim de arquivo);
  - config por arquivo gen_sources.json OU pela constante SOURCES abaixo.

Uso:
    python generate_context.py
    python generate_context.py --output context.md --sources gen_sources.json
    python generate_context.py --budget-kb 30

Config via JSON (gen_sources.json):
    {
      "sources": {
        "README.md": null,
        "docs/*.md": null,
        "docs/spec.md": ["## Resumo", "## Resultados"]
      },
      "max_chars_per_section": 4000,
      "max_chars_full_file": 8000,
      "budget_kb": 40
    }
null = arquivo inteiro (ate o limite). Lista = apenas essas secoes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Fallback se nao houver gen_sources.json. Edite aqui ou use o JSON.
SOURCES: dict[str, list[str] | None] = {
    "README.md": None,
}
MAX_CHARS_PER_SECTION = 4000
MAX_CHARS_FULL_FILE = 8000
BUDGET_KB = 40  # teto total do context.md


def extract_section(text: str, heading: str, max_chars: int) -> str:
    """Extrai do heading ate o proximo heading de nivel <= ao dele (ou EOF)."""
    idx = text.find(heading)
    if idx == -1:
        return ""
    level = len(re.match(r"#+", heading.strip()).group(0))
    rest = text[idx + len(heading):]
    # proximo heading com 1..level '#'
    nxt = re.search(rf"^#{{1,{level}}}\s", rest, re.MULTILINE)
    section = (heading + rest[: nxt.start()]).strip() if nxt else (heading + rest).strip()
    if len(section) > max_chars:
        section = section[:max_chars].rstrip() + "\n\n*(... secao truncada)*"
    return section


def process_file(path: Path, headings: list[str] | None,
                 max_section: int, max_full: int) -> str:
    if not path.exists():
        print(f"  AVISO: {path} nao existe, pulando.", file=sys.stderr)
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        print(f"  AVISO: nao consegui ler {path.name}: {e}", file=sys.stderr)
        return ""

    if headings is None:
        out = text[:max_full]
        if len(text) > max_full:
            out += "\n\n*(... arquivo truncado)*"
        return out

    parts = []
    for h in headings:
        sec = extract_section(text, h, max_section)
        if sec:
            parts.append(sec)
        else:
            print(f"  AVISO: heading '{h}' nao achado em {path.name}", file=sys.stderr)
    return "\n\n".join(parts)


def expand_sources(sources: dict, root: Path) -> list[tuple[Path, list[str] | None]]:
    """Resolve globs preservando a config de headings."""
    resolved: list[tuple[Path, list[str] | None]] = []
    seen: set[Path] = set()
    for pattern, headings in sources.items():
        matches = sorted(root.glob(pattern)) if any(c in pattern for c in "*?[") else [root / pattern]
        for m in matches:
            mp = m.resolve()
            if mp in seen:
                continue
            seen.add(mp)
            resolved.append((m, headings))
    return resolved


def load_sources_config(path: Path):
    if not path.exists():
        return SOURCES, MAX_CHARS_PER_SECTION, MAX_CHARS_FULL_FILE, BUDGET_KB
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return (
        cfg.get("sources", SOURCES),
        cfg.get("max_chars_per_section", MAX_CHARS_PER_SECTION),
        cfg.get("max_chars_full_file", MAX_CHARS_FULL_FILE),
        cfg.get("budget_kb", BUDGET_KB),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default=str(ROOT / "context.md"))
    ap.add_argument("--sources", default=str(ROOT / "gen_sources.json"))
    ap.add_argument("--budget-kb", type=float, default=None)
    args = ap.parse_args()

    sources, max_section, max_full, budget_kb = load_sources_config(Path(args.sources))
    if args.budget_kb is not None:
        budget_kb = args.budget_kb
    budget_chars = int(budget_kb * 1024)

    print("Gerando context.md...")
    blocks: list[str] = []
    total = 0
    for path, headings in expand_sources(sources, ROOT):
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"  {rel}...")
        content = process_file(path, headings, max_section, max_full)
        if not content:
            continue
        block = f"# FONTE: {rel}\n\n{content}"
        if total + len(block) > budget_chars:
            remaining = budget_chars - total
            if remaining > 500:
                blocks.append(block[:remaining].rstrip() + "\n\n*(... orcamento atingido)*")
            print(f"  ORCAMENTO ({budget_kb:.0f} KB) atingido em {rel}. Parando.", file=sys.stderr)
            break
        blocks.append(block)
        total += len(block)

    if not blocks:
        print("ERRO: nenhum conteudo gerado. Confira os caminhos.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    out_path.write_text("\n\n---\n\n".join(blocks), encoding="utf-8")
    kb = out_path.stat().st_size / 1024
    print(f"\nGerado: {out_path} ({kb:.1f} KB / teto {budget_kb:.0f} KB)")
    print("Revise e remova qualquer informacao sensivel antes de apresentar.")


if __name__ == "__main__":
    main()
