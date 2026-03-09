#!/usr/bin/env python3
"""
install_schema.py — Set up Dgraph schema for AgentMemory with relevance tracking.

Run this once to add the new fields:
- recall_count
- usefulness_score
- usefulness_count
- last_recalled_at

Usage:
  python3 scripts/install_schema.py
"""

import requests
import sys

DGRAPH = "http://localhost:8080"


def log(msg):
    print(f"[install_schema] {msg}", file=sys.stderr)


def main():
    log("Setting up Dgraph schema...")
    
    # Core AgentMemory schema with new relevance fields
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

# New: Relevance & Usefulness
AgentMemory.recall_count: int @index .
AgentMemory.usefulness_score: float .
AgentMemory.usefulness_count: int .
AgentMemory.last_recalled_at: datetime .
"""
    
    # Apply core schema
    r = requests.post(f"{DGRAPH}/alter", data=schema, headers={"Content-Type": "text/plain"})
    if r.status_code in (200, 201):
        log("✓ AgentMemory schema applied")
    else:
        log(f"⚠ Schema apply returned {r.status_code}: {r.text[:200]}")
    
    # Knowledge graph schemas
    kg_schema = """
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
    
    r = requests.post(f"{DGRAPH}/alter", data=kg_schema, headers={"Content-Type": "text/plain"})
    if r.status_code in (200, 201):
        log("✓ Knowledge graph schema applied")
    else:
        log(f"⚠ KG schema returned {r.status_code}")
    
    # Verify setup
    r = requests.get(f"{DGRAPH}/health")
    if r.status_code == 200:
        log("✓ Dgraph is healthy")
        print("\n✅ Schema installation complete!")
        print("\nNew fields available:")
        print("  - recall_count: how many times a memory was retrieved")
        print("  - usefulness_score: average usefulness rating (-1 to 1)")
        print("  - usefulness_count: number of usefulness ratings")
        print("  - last_recalled_at: timestamp of last retrieval")
    else:
        log("✗ Dgraph health check failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
