# OpenClaw Dgraph Memory — Second Brain for AI Agents

A semantic memory system for OpenClaw agents using Dgraph as the knowledge graph backend. Provides episodic, semantic, and procedural memory storage with full-text search.

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
│  - Syncs to SQLite for caching                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Dgraph (localhost:8080)                        │
│  - AgentMemory type: agent, memory_type, content, tags     │
│  - Person/Project/SOP/Insight nodes                       │
│  - Vector embeddings via Ollama                            │
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

# Test connection
python3 scripts/test_connection.py
```

### Option 2: Standalone Plugin

```bash
# Clone anywhere
git clone https://github.com/tardis-create/openclaws-tardis-brain.git /path/to/brain-plugin

# Add to your OpenClaw config (openclaw.json)
{
  "skills": {
    "install": {
      "nodeManager": "npm"
    },
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

# Search memories
python3 scripts/dgraph-qmd.py search \
  --agent tardis \
  --query "infrastructure deployment rules"

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

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DGRAPH_URL` | `http://localhost:8080` | Dgraph server endpoint |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server endpoint |
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model |
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

### AgentMemory Type

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
| `dgraph-qmd.py` | QMD protocol implementation for OpenClaw |
| `brain_query.py` | Knowledge graph queries (people, projects, SOPs) |
| `memory_embed.py` | Semantic embedding + storage |
| `memory_prune.py` | Cleanup old/low-importance memories |

## Stats (Example)

```
tardis:  326 episodic, 8 semantic
bhagwan: 204 episodic
amy:      57 episodic
mirror:    4 episodic
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
- Ensure Dgraph has data: `python3 scripts/dgraph-qmd.py list`
- Run prune to clean stale entries

## Contributing

1. Fork the repo
2. Create a feature branch
3. Submit a PR

## License

MIT — See LICENSE file.

---

Built with ❤️ for the OpenClaw ecosystem. Bigger on the inside.
