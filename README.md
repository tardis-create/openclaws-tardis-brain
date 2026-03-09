# OpenClaw Dgraph Memory — Second Brain for AI Agents

A semantic memory system for OpenClaw agents using Dgraph as the knowledge graph backend. Provides episodic, semantic, and procedural memory storage with full-text search, relevance tracking, and intelligent reranking.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![OpenClaw](https://img.shields.io/badge/OpenClaw-2026+-green.svg)

## Overview

This plugin gives AI agents a **second brain** — persistent, searchable memory that survives across sessions.

### Features

- **Episodic Memory**: Session transcripts, decisions, events
- **Semantic Memory**: Facts, people, projects, SOPs
- **Procedural Memory**: How-to guides, workflows, agent rules
- **Full-Text Search**: Query memories by keyword or semantic similarity
- **Knowledge Graph**: Entities linked by relationships (person→project, agent→task)
- **QMD Integration**: Plugs into OpenClaw's native memory search pipeline
- **Relevance Tracking**: Know what's remembered often vs forgotten
- **Usefulness Scoring**: Track which memories are actually useful
- **Semantic Reranking**: Cross-encoder reranking for better search results

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     OpenClaw Agent                          │
│  (memory_store, memory_recall, memory_search tools)       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              dgraph-qmd (QMD Backend)                      │
│  - Implements OpenClaw's QMD protocol                      │
│  - Routes queries to Dgraph                                │
│  - Reranks results using cross-encoder                    │
│  - Tracks relevance/usefulness                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Dgraph (localhost:8080)                        │
│  - AgentMemory type: agent, memory_type, content, tags    │
│  - Person/Project/SOP/Insight nodes                        │
│  - Vector embeddings via Ollama                            │
│  - Relevance & usefulness scores                           │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Dgraph** running on `http://localhost:8080`
2. **Ollama** running on `http://localhost:11434` (for embeddings)
3. **OpenClaw** installed

### Install Dgraph

```bash
# Docker
docker run -d --name dgraph -p 8080:8080 -p 9080:9080 dgraph/standalone:v24.0.1

# Or binary
curl -s https://install.dgraph.io | bash
dgraph start
```

### Install Ollama + Embedding Model

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull embedding model
ollama pull nomic-embed-text

# Pull reranker model (optional, for better search)
ollama pull cross-encoder
```

## Installation

### Option 1: Quick Install (Recommended)

```bash
# Clone into OpenClaw skills
cd ~/.openclaw/skills
git clone https://github.com/tardis-create/openclaws-tardis-brain.git brain

# Configure Dgraph endpoint
export DGRAPH_URL=http://localhost:8080
export OLLAMA_URL=http://localhost:11434

# Run installer (sets up schema)
python3 scripts/install_schema.py

# Test connection
python3 scripts/brain_query.py test
```

### Option 2: Standalone Plugin

```bash
# Clone anywhere
git clone https://github.com/tardis-create/openclaws-tardis-brain.git /path/to/brain-plugin

# Add to your OpenClaw config (openclaw.json)
{
  "skills": {
    "entries": {
      "brain": {
        "path": "/path/to/brain-plugin",
        "enabled": true
      }
    }
  }
}
```

## Usage

### From OpenClaw

The agent tools are automatically available:

```
memory_store text="..." category="episodic" importance=0.8
memory_search query="what did we decide about X"
memory_recall limit=5
```

### Command Line

```bash
# Store a memory
python3 scripts/dgraph-qmd.py store \
  --agent tardis \
  --type episodic \
  --title "NDV-B07 Fix" \
  --content "Fixed NIDAVELLIR_API env var..." \
  --tags "nidavellir,bugfix"

# Search memories (with reranking)
python3 scripts/dgraph-qmd.py search \
  --agent tardis \
  --query "infrastructure deployment rules"

# Track that a memory was useful (call after using a memory)
python3 scripts/dgraph-qmd.py useful \
  --memory-id <uid> \
  --score 1   # +1 for useful, -1 for not useful

# Get memory stats (relevance/usefulness)
python3 scripts/dgraph-qmd.py stats --agent tardis

# Add a person to knowledge graph
python3 scripts/brain_query.py add-person \
  --id "mit" \
  --name "MIT" \
  --role "CMO/Product Lead" \
  --phone "+919879208812" \
  --context "Contact for marketing decisions"

# Query knowledge graph
python3 scripts/brain_query.py --query "MIT contact outreach"
```

## Relevance & Usefulness Tracking

### How It Works

Every time a memory is retrieved during search, we increment its `recall_count`. When you mark it as useful (or not), we update its `usefulness_score`.

### Queries

```bash
# Most remembered memories (high recall)
python3 scripts/dgraph-qmd.py stats --agent tardis --sort recall

# Most useful memories
python3 scripts/dgraph-qmd.py stats --agent tardis --sort usefulness

# Least useful (needs review)
python3 scripts/dgraph-qmd.py stats --agent tardis --sort "least-useful"

# Memories never recalled (potential gaps)
python3 scripts/dgraph-qmd.py stats --agent tardis --sort never-recalled
```

### Marking Usefulness

After using a memory in your response:

```bash
# This memory was useful
python3 scripts/dgraph-qmd.py useful --memory-id <uid> --score 1

# This memory wasn't relevant
python3 scripts/dgraph-qmd.py useful --memory-id <uid> --score -1

# Bulk update (after a search session)
python3 scripts/dgraph-qmd.py useful-bulk --memory-ids "uid1,uid2,uid3" --scores "1,-1,1"
```

## Reranking

The search automatically reranks results using a cross-encoder model for better relevance.

### How It Works

1. Initial retrieval: Vector similarity search (fast)
2. Reranking: Cross-encoder scores all results against query
3. Final ranking: Combines vector similarity + cross-encoder scores

### Configuration

```bash
# Disable reranking (faster but less accurate)
export RERANK_ENABLED=false

# Set reranker model
export RERANK_MODEL=cross-encoder

# Adjust reranking weight (0-1)
export RERANK_WEIGHT=0.5
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DGRAPH_URL` | `http://localhost:8080` | Dgraph server endpoint |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server endpoint |
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `RERANK_MODEL` | `cross-encoder` | Reranker model |
| `RERANK_ENABLED` | `true` | Enable reranking |
| `RERANK_WEIGHT` | `0.5` | Reranking weight (0-1) |
| `OPENCLAW_AGENT_ID` | `tardis` | Default agent ID |

### OpenClaw Config

Add to `agents.defaults` in your `openclaw.json`:

```json
{
  "memory": {
    "backend": "qmd",
    "qmd": {
      "command": "/path/to/dgraph-qmd.py",
      "searchMode": "vsearch"
    }
  }
}
```

## Schema

### AgentMemory Type (Enhanced)

```graphql
type AgentMemory {
  id: string @index(hash) @upsert
  agent: string @index(hash)
  memory_type: string @index(term)  # episodic, semantic, procedural
  title: string @index(term)
  content: string @index(fulltext)
  tags: [string] @index(term)
  importance: float
  embedding: [float]
  stored_at: datetime
  source_file: string
  summary: string
  
  # New: Relevance & Usefulness
  recall_count: int @index
  usefulness_score: float
  last_recalled_at: datetime
  usefulness_count: int
}
```

### Knowledge Graph Types

```graphql
type Person {
  id: string @index(hash) @upsert
  name: string @index(term)
  role: string
  phone: string
  email: string
  context: string
  tags: [string]
  projects: [Project]
  sops: [SOP]
}

type Project {
  id: string @index(hash) @upsert
  name: string @index(term)
  description: string
  status: string  # active, paused, done
  domain: string
}

type SOP {
  id: string @index(hash) @upsert
  title: string @index(term)
  content: string @index(fulltext)
  domain: string
  tags: [string]
}

type Insight {
  id: string @index(hash) @upsert
  title: string @index(term)
  content: string @index(fulltext)
  domain: string
  tags: [string]
}
```

## Scripts

| Script | Purpose |
|--------|---------|
| `dgraph-qmd.py` | QMD protocol + search + reranking + stats |
| `brain_query.py` | Knowledge graph queries (people, projects, SOPs) |
| `memory_embed.py` | Semantic embedding + storage |
| `memory_prune.py` | Cleanup old/low-importance memories |
| `install_schema.py` | Set up Dgraph schema with new fields |

## Stats Example

```
Agent: tardis
═══════════════════════════════════════════════════════
Total Memories: 334
Total Recalls:  1,247
Avg Usefulness: 0.72

Top 5 Most Remembered:
  1. "NDV-B07 Fix"          (recalls: 23, usefulness: 0.85)
  2. "infra rules cloudflare" (recalls: 19, usefulness: 0.91)
  3. "agent dispatch rules"  (recalls: 15, usefulness: 0.78)
  4. "MIT contact details"  (recalls: 12, usefulness: 0.95)
  5. "PocketBase schema"    (recalls: 11, usefulness: 0.67)

Never Recalled (needs review):
  - "old deployment SOP"
  - "deprecated API keys"
  - "legacy workflow X"
```

## Troubleshooting

### Dgraph connection refused

```bash
# Check Dgraph is running
curl http://localhost:8080/health

# Start if needed
docker start dgraph
```

### Ollama embedding errors

```bash
# Verify Ollama is running
ollama list

# Pull embedding model if missing
ollama pull nomic-embed-text
```

### Memory search returns nothing

- Check agent ID matches (case-sensitive)
- Ensure Dgraph has data: `python3 scripts/dgraph-qmd.py stats`
- Run: `python3 scripts/install_schema.py` to add new fields

## Contributing

1. Fork the repo
2. Create a feature branch
3. Submit a PR

## License

MIT — See LICENSE file.

---

Built with ❤️ for the OpenClaw ecosystem. Bigger on the inside.
