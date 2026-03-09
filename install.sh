#!/bin/bash
# install.sh — Set up OpenClaw Dgraph Memory Plugin

set -e

echo "🧠 OpenClaw Dgraph Memory Plugin Installer"
echo "=========================================="

# Check prerequisites
echo ""
echo "Checking prerequisites..."

# Check Dgraph
if ! curl -s http://localhost:8080/health >/dev/null 2>&1; then
    echo "❌ Dgraph not running at http://localhost:8080"
    echo "   Install: docker run -d --name dgraph -p 8080:8080 dgraph/standalone:v24.0.1"
    exit 1
fi
echo "✓ Dgraph connected"

# Check Ollama
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "❌ Ollama not running at http://localhost:11434"
    echo "   Install: curl -fsSL https://ollama.ai/install.sh | sh"
    exit 1
fi
echo "✓ Ollama connected"

# Check/pull embedding model
if ! ollama list | grep -q nomic-embed-text; then
    echo "📦 Pulling nomic-embed-text model..."
    ollama pull nomic-embed-text
fi
echo "✓ Embedding model ready"

# Set up schema
echo ""
echo "Setting up Dgraph schema..."
python3 <<'PY'
import requests

DGRAPH = "http://localhost:8080"

schema = """
AgentMemory: uid @index(hash) @upsert .
AgentMemory.agent: string @index(hash) .
AgentMemory.memory_type: string @index(term) .
AgentMemory.title: string @index(term) .
AgentMemory.content: string @index(fulltext) .
AgentMemory.tags: [string] @index(term) .
AgentMemory.importance: float .
AgentMemory.embedding: [float] .
AgentMemory.stored_at: datetime .
AgentMemory.source_file: string .
AgentMemory.summary: string .

Person: uid @index(hash) @upsert .
Person.id: string @index(hash) .
Person.name: string @index(term) .
Person.role: string .
Person.phone: string .
Person.email: string .
Person.context: string .
Person.tags: [string] @index(term) .

Project: uid @index(hash) @upsert .
Project.id: string @index(hash) .
Project.name: string @index(term) .
Project.description: string .
Project.status: string @index(term) .
Project.domain: string @index(term) .

SOP: uid @index(hash) @upsert .
SOP.id: string @index(hash) .
SOP.title: string @index(term) .
SOP.content: string @index(fulltext) .
SOP.domain: string @index(term) .
SOP.tags: [string] @index(term) .

Insight: uid @index(hash) @upsert .
Insight.id: string @index(hash) .
Insight.title: string @index(term) .
Insight.content: string @index(fulltext) .
Insight.domain: string @index(term) .
Insight.tags: [string] @index(term) .
"""

# Use alter endpoint
r = requests.post(f"{DGRAPH}/alter", data=schema, headers={"Content-Type": "text/plain"})
if r.status_code in (200, 201):
    print("✓ Schema applied")
else:
    print(f"Schema warning: {r.status_code} - may already exist")

# Add indexes for AgentMemory
indexes = """
AgentMemory.content: string @index(fulltext) .
"""
r = requests.post(f"{DGRAPH}/alter", data=indexes, headers={"Content-Type": "text/plain"})
print("✓ Indexes configured")
PY

# Create symlink if using default OpenClaw location
OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw}"
SKILLS_DIR="$OPENCLAW_DIR/skills"

if [ -d "$SKILLS_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    ln -sf "$SCRIPT_DIR" "$SKILLS_DIR/brain" 2>/dev/null || true
    echo ""
    echo "✓ Linked to $SKILLS_DIR/brain"
fi

echo ""
echo "🎉 Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Add to openclaw.json:"
echo '     "skills": { "entries": { "brain": { "path": "'"$SKILLS_DIR/brain"'" } } }'
echo ""
echo "  2. Test: python3 scripts/brain_query.py test"
echo ""
echo "  3. Store a memory:"
echo '     python3 scripts/brain_query.py add-person --id "john" --name "John Doe" --role "CTO"'
