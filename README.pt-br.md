# agent-cortex

[![CI](https://github.com/ye-sandbox/agent-cortex/actions/workflows/ci.yml/badge.svg)](https://github.com/ye-sandbox/agent-cortex/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
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
│  - Extração de metadados (repo, breadcrumbs, tags, ciclo de vida, scope│
│  - FastEmbed local em CPU (Perfis adaptativos: high | balanced | low)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    BUSCA HÍBRIDA & RERANKING DE 2 ETAPAS               │
│  Etapa 1: LanceDB Embutido (Denso IVF-PQ + Tantivy BM25 + Fusão RRF)   │
│  Etapa 2: Cross-Encoder Reranker (Precisão cirúrgica em balanced/high) │
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
4. **Arquitetura Dual-Mode:** Opera localmente nas estações (modo embutido) ou conecta remotamente a um hub central no homelab via HTTP/REST + Bearer Token.

---

## 🚀 Início Rápido

### Pré-requisitos
- Python 3.14+
- [`uv`](https://github.com/astral-sh/uv)

### Instalação
```bash
git clone https://github.com/ye-sandbox/agent-cortex.git
cd agent-cortex
uv sync
```

### Inicialização e Pré-carregamento de Modelos
```bash
# Inicializa diretórios, gera config.yaml e baixa os modelos padrão (balanced)
uv run cortex bootstrap

# Baixa pesos para perfil de alta precisão antecipadamente
uv run cortex models download --profile high
```

### Sincronizando Repositórios
```bash
# Varre e indexa um diretório de projetos (descoberta automática de repositórios git)
uv run cortex sync ~/github/ye-sandbox/

# Ou indexa um repositório específico
uv run cortex sync ~/github/ye-sandbox/sentinel-deals-backend
```

### Buscando no Portfólio
```bash
# Busca semântica em linguagem natural
uv run cortex search "reconexão automática websocket backoff"

# Filtro por categoria, escopo ou repositório
uv run cortex search "deals pagination endpoint" --category contract --limit 3

# Saída em JSON para scripts e subshells de agentes
uv run cortex search "SSE streaming retry" --json
```

### Dashboard Interativo de Topologia

Gere um arquivo HTML autocontido com o grafo de dependências do portfolio:

```bash
uv run cortex topology dashboard
```

Abra o arquivo gerado em `~/.local/share/agent-cortex/exports/topology-dashboard.html` no navegador. O dashboard opera offline e permite buscar repositórios, filtrar por peso de aresta, focar em ciclos de dependência e inspecionar detalhes de nós e arestas.

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
- **Recuperação Semântica**:
  - `cortex_search(query, category?, repo?, scope?, limit?)`: Executa busca híbrida e retorna snippets com links `file://`.
  - `cortex_get_repo_contracts(repo)`: Recupera contratos, rotas OpenAPI, serviços Docker Compose e assinaturas AST de um repositório.
  - `cortex_list_technologies(tech_name)`: Identifica quais projetos utilizam determinada ferramenta ou biblioteca.
  - `cortex_version()`: Retorna a versão ativa e identidade do sistema `agent-cortex`.
- **Topologia & Acoplamento**:
  - `cortex_get_portfolio_topology(format?, direction?, min_weight?)`: Exporta grafo de dependência do portfólio (Mermaid, DOT, Cytoscape).
  - `cortex_get_dependency_matrix(min_weight?)`: Retorna métricas de acoplamento aferente/eferente e índices de instabilidade.
  - `cortex_get_code_dependencies(repo?, target_repo?, symbol?, dependency_type?, limit?)`: Consulta relações de dependência AST em baixo nível.
- **Drift & Evolução de Contratos**:
  - `cortex_get_contract_drift(repo?, breaking_only?, cross_repo_only?)`: Audita quebras de contrato arquitetural entre repositórios.
  - `cortex_get_contract_timeline(repo?, contract_type?, change_kind?, breaking_only?, limit?)`: Retorna linha do tempo histórica de evolução dos contratos.
  - `cortex_synthesize_changelog(repo?, group_by?, breaking_only?, limit?)`: Sintetiza changelog estruturado em markdown a partir do histórico de contratos.
- **Impacto & Intenção de Mudança**:
  - `cortex_simulate_blast_radius(repo, symbol?, file_path?, change_kind?, max_depth?)`: Simula raio de impacto multi-hop com pontuação de risco e recomendações para agentes.
  - `cortex_trace_impact(repo, symbol?, file_path?, max_depth?)`: Rastreia chamadores transitivos no grafo de dependência do portfólio.
  - `cortex_simulate_change_intent(...)`: Simula planos de migração e detecta potenciais violações de contrato.
  - `cortex_generate_contract_patches(...)`: Gera patches unified diff compatíveis com `git apply` para os repositórios consumidores afetados.

---

## ⚙️ Configuração (`config.yaml`)

```yaml
profile: "balanced"                           # "high" | "balanced" | "low" | "code" | "custom"

custom_profile:
  name: "custom"
  embedding_model: "BAAI/bge-small-en-v1.5"
  embedding_dim: 384
  reranker_model: "BAAI/bge-reranker-base"
  reranker_enabled: true
  top_k_rerank: 20
  max_threads: 4

storage:
  data_dir: "~/.local/share/agent-cortex/data"

sources:
  auto_discover:
    enabled: true
    roots:
      - "~/github/ye-sandbox"
    max_depth: 3
  repositories:
    - path: "~/github/ye-sandbox/sentinel-deals-backend"
      default_scope: "internal"
    - path: "~/github/ye-sandbox/clipflow-backend"
      default_scope: "internal"

retrieval:
  k: 60
  weight_dense: 0.65
  weight_sparse: 0.35
  archived_penalty: 0.6
  default_limit: 10

remote:
  hub_url: "http://homelab-mini.local:8000"
  api_key: null                               # Ou defina via variável de ambiente CORTEX_API_KEY
```

---

## 📄 Licença

MIT © [ye-sandbox](https://github.com/ye-sandbox)
