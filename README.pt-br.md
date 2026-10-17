# agent-cortex

[![CI](https://github.com/ye-sandbox/agent-cortex/actions/workflows/ci.yml/badge.svg)](https://github.com/ye-sandbox/agent-cortex/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Architecture: In--Process LanceDB](https://img.shields.io/badge/Storage-LanceDB%20Embedded-green.svg)](https://lancedb.github.io/lancedb/)

🌐 **[English](README.md) | Português**

**Motor de busca semântica cross-repo e memória de longo prazo para agentes de IA autônomos e desenvolvedores.**

O `agent-cortex` transforma múltiplos repositórios em uma memória viva de longo prazo (*Long-Term Memory - LTM*). Ele permite descobrir instantaneamente em linguagem natural onde e como soluções arquiteturais passadas, interfaces reutilizáveis e contratos de sistemas foram implementados em dezenas de projetos, sem a sobrecarga de daemons pesados.

---

## ⚡ Por que o agent-cortex?

Em ecossistemas com múltiplos repositórios e agentes autônomos (Antigravity, Cursor, Claude Code, Dev Trinity), o desenvolvimento sofre frequentemente com a **amnésia organizacional**:
- Planners reinventam a roda por não terem visibilidade dos padrões já consolidados em repositórios irmãos.
- Desenvolvedores perdem tempo e foco navegando por dezenas de diretórios locais para lembrar onde um problema técnico complexo foi resolvido.
- Contratos e convenções divergem entre os microsserviços.

O `agent-cortex` resolve isso indexando continuamente documentação curada, contratos OpenAPI e manifests de infraestrutura, expondo busca híbrida em menos de 50ms via terminal CLI e MCP Server.

---

## 🏛️ Arquitetura

```
┌────────────────────────────────────────────────────────────────────────┐
│                        REPOSITÓRIOS DA ORGANIZAÇÃO                     │
│   ia-maestri   │   agent-guard   │   taskctl   │  satélites / serviços │
│   (docs/specs) │   (invariants)  │  (contracts)│    (compose/apis)     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Rastreamento Git Diff (Incremental)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     ENGINE DE INGESTÃO DO AGENT-CORTEX                 │
│  - Chunking semântico (Markdown headers, rotas OpenAPI, Compose svcs)  │
│  - Extração de metadados (repo, breadcrumbs, tags, ciclo de vida)      │
│  - FastEmbed local em CPU (BGE-M3 / ONNX Runtime, zero PyTorch/GPU)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    BUSCA HÍBRIDA & RERANKING DE 2 ETAPAS               │
│  Etapa 1: LanceDB Embutido (Denso IVF-PQ + Tantivy BM25 + Fusão RRF)   │
│  Etapa 2: Cross-Encoder Reranker (BGE-Reranker para precisão cirúrgica)│
│  Armazenamento: Apache Arrow / Parquet em disco local (Zero RAM idle)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌───────────────────────┐                       ┌───────────────────────┐
│     CLI DE TERMINAL   │                       │   MCP SERVER (stdio)  │
│  cortex search ...    │                       │  Planners, Antigravity│
│  Saída: ANSI / JSON   │                       │  e Agentes Autônomos  │
└───────────────────────┘                       └───────────────────────┘
```

### Invariantes Arquiteturais:
1. **In-Process & Zero Daemon:** Construído sobre LanceDB embutido e FastEmbed ONNX. Consome 0MB de RAM em repouso e inicia em < 30ms.
2. **Busca Híbrida em 2 Etapas:** Combina Vetor Denso + Busca Léxica BM25 via Reciprocal Rank Fusion (RRF), seguido por um Reranker Cross-Encoder para eliminar falsos positivos.
3. **Isolamento de Dados Privados:** O motor é público e open-source; todos os vetores e trechos de código indexados residem fora do repositório Git em diretórios locais (`~/.local/share/agent-cortex/`).
4. **Arquitetura Dual-Mode:** Opera localmente na máquina do desenvolvedor ou conecta remotamente a um hub central no homelab.

---

## 🚀 Uso Rápido

### Pré-requisitos
- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) (recomendado) ou `pip`

### Instalação
```bash
git clone https://github.com/ye-sandbox/agent-cortex.git
cd agent-cortex
uv sync
```

### Indexação de Repositórios
```bash
# Escanear e indexar todos os repositórios em uma pasta
uv run cortex sync ~/github/ye-sandbox/

# Ou indexar um único repositório
uv run cortex sync ~/github/ye-sandbox/poc-mod-maestri
```

### Busca Semântica
```bash
# Busca semântica em linguagem natural
uv run cortex search "reconexão automática websocket backoff"

# Filtro por categoria ou repositório específico
uv run cortex search "victorialogs integration" --category infra --limit 3

# Saída em JSON para scripts e subshells de agentes
uv run cortex search "SSE streaming retry" --json
```

---

## 🤖 Integração via MCP (Model Context Protocol)

O `agent-cortex` inclui um servidor MCP stdio nativo para integração direta em agentes e IDEs:

Adicione na configuração do seu agente (`antigravity.json`, `claude_desktop_config.json`, ou Cursor):
```json
{
  "mcpServers": {
    "cortex": {
      "command": "uv",
      "args": ["--directory", "/path/to/agent-cortex", "run", "cortex-mcp"]
    }
  }
}
```

### Ferramentas MCP Disponíveis:
- **`cortex_search(query, category?, repo?, limit?)`**: Executa busca híbrida e retorna snippets com links `file://`.
- **`cortex_get_repo_contracts(repo)`**: Recupera contratos, rotas e interfaces expostas por um repositório.
- **`cortex_list_technologies(tech_name)`**: Identifica quais projetos utilizam determinada ferramenta ou biblioteca.

---

## 📄 Licença

MIT © [ye-sandbox](https://github.com/ye-sandbox)
