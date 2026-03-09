# SKILL: Brain — Dgraph Memory for OpenClaw

Semantic memory and knowledge graph for OpenClaw agents. Provides episodic, semantic, and procedural memory storage with full-text search.

## When to use

Use this skill when you need to:
- Remember decisions, conversations, or events across sessions
- Query knowledge about people, projects, or SOPs
- Store insights that persist beyond session history
- Search memories by keyword or semantic similarity

## How to use

```bash
# Search agent memories
python3 <skill_path>/scripts/brain_query.py "query here"

# Test connection
python3 <skill_path>/scripts/brain_query.py test

# Add a person
python3 <skill_path>/scripts/brain_query.py add-person --id "mit" --name "MIT" --role "CMO" --phone "+919879208812"

# Add a project
python3 <skill_path>/scripts/brain_query.py add-project --id "orthopulse" --name "OrthoPulse" --domain "healthcare"

# Add an SOP
python3 <skill_path>/scripts/brain_query.py add-sop --id "deploy-sop" --title "Deploy to Cloudflare" --domain "devops"

# List all
python3 <skill_path>/scripts/brain_query.py list --type people
python3 <skill_path>/scripts/brain_query.py list --type projects
python3 <skill_path>/scripts/brain_query.py list --type sops
```

## Prerequisites

1. **Dgraph** at `http://localhost:8080`
2. **Ollama** at `http://localhost:11434` with `nomic-embed-text`

## Configuration

Set environment variables:
```bash
export DGRAPH_URL=http://localhost:8080
export OLLAMA_URL=http://localhost:11434
```
