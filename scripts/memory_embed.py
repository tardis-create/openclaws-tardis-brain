#!/usr/bin/env python3
"""
memory_embed.py — Tardis semantic memory layer
Embeds text via Ollama nomic-embed-text, stores/searches in Dgraph AgentMemory.

Usage:
  python3 memory_embed.py store --text "..." --agent tardis --type session --tags "tag1,tag2"
  python3 memory_embed.py search --query "..." --agent tardis --topk 5
  python3 memory_embed.py list --agent tardis --limit 20
"""

import argparse, json, sys, uuid, hashlib
from datetime import datetime, timezone

OLLAMA_URL = "http://localhost:11434"
DGRAPH_URL = "http://localhost:8080"
EMBED_MODEL = "nomic-embed-text"


def embed(text: str) -> list[float]:
    import urllib.request
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/embeddings", data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["embedding"]


def dgraph_mutate(mutations: list[dict]) -> dict:
    import urllib.request
    payload = json.dumps({"mutations": mutations}).encode()
    req = urllib.request.Request(f"{DGRAPH_URL}/graphql/worker/startTs",
                                  data=payload, headers={"Content-Type": "application/json"})
    # Use GraphQL mutation instead
    return dgraph_graphql(build_mutation(mutations[0]) if mutations else "")


def dgraph_graphql(query: str, variables: dict = None) -> dict:
    import urllib.request
    body = {"query": query}
    if variables:
        body["variables"] = variables
    payload = json.dumps(body).encode()
    req = urllib.request.Request(f"{DGRAPH_URL}/graphql",
                                  data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def store_memory(text: str, agent: str, memory_type: str, title: str = None,
                 tags: list[str] = None, importance: float = 0.7,
                 source_file: str = None, summary: str = None) -> str:
    """Embed text and store in Dgraph AgentMemory. Returns the memory ID."""
    print(f"Embedding: {text[:80]}...", file=sys.stderr)
    emb = embed(text)

    mem_id = hashlib.md5(f"{agent}:{text[:200]}:{datetime.now().isoformat()}".encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()

    mutation = """
mutation AddMemory($input: [AddAgentMemoryInput!]!) {
  addAgentMemory(input: $input) {
    agentMemory { id }
  }
}
"""
    variables = {
        "input": [{
            "id": mem_id,
            "agent": agent,
            "memory_type": memory_type,
            "date": now[:10],
            "title": title or text[:80],
            "content": text,
            "summary": summary or text[:200],
            "tags": tags or [],
            "importance": importance,
            "source_file": source_file or "",
            "embedding": emb,
            "stored_at": now,
        }]
    }

    result = dgraph_graphql(mutation, variables)
    if result.get("errors"):
        print(f"Error: {result['errors']}", file=sys.stderr)
        sys.exit(1)

    print(f"Stored: {mem_id}", file=sys.stderr)
    return mem_id


def search_memories(query: str, agent: str = None, topk: int = 5) -> list[dict]:
    """Semantic search over AgentMemory using embedding similarity (HNSW cosine)."""
    emb = embed(query)

    gql = """
query Search($vec: [Float!]!, $topK: Int!) {
  querySimilarAgentMemoryByEmbedding(by: embedding, topK: $topK, vector: $vec) {
    id agent memory_type title summary tags importance date stored_at
  }
}
"""
    result = dgraph_graphql(gql, {"vec": emb, "topK": topk})
    memories = result.get("data", {}).get("querySimilarAgentMemoryByEmbedding", []) if result else []

    # Filter by agent if specified
    if agent:
        memories = [m for m in memories if m.get("agent") == agent]

    return [{
        "id": m.get("id", ""),
        "agent": m.get("agent", ""),
        "type": m.get("memory_type", ""),
        "title": m.get("title", ""),
        "summary": m.get("summary", ""),
        "tags": m.get("tags", []),
        "importance": m.get("importance", 0),
        "date": m.get("date", ""),
    } for m in memories]


def list_memories(agent: str = None, limit: int = 20) -> list[dict]:
    """List recent memories."""
    filter_clause = f'filter: {{agent: {{eq: "{agent}"}}}}' if agent else ""
    query = f"""
{{
  queryAgentMemory({filter_clause} first: {limit}, order: {{desc: stored_at}}) {{
    id agent memory_type title summary tags importance date stored_at
  }}
}}
"""
    result = dgraph_graphql(query)
    return result.get("data", {}).get("queryAgentMemory", [])


def main():
    parser = argparse.ArgumentParser(description="Tardis semantic memory")
    sub = parser.add_subparsers(dest="cmd")

    # store
    s = sub.add_parser("store", help="Store a memory")
    s.add_argument("--text", required=True)
    s.add_argument("--agent", default="tardis")
    s.add_argument("--type", default="fact")
    s.add_argument("--title")
    s.add_argument("--summary")
    s.add_argument("--tags", default="")
    s.add_argument("--importance", type=float, default=0.7)
    s.add_argument("--source")

    # search
    s2 = sub.add_parser("search", help="Semantic search")
    s2.add_argument("--query", required=True)
    s2.add_argument("--agent")
    s2.add_argument("--topk", type=int, default=5)

    # list
    s3 = sub.add_parser("list", help="List memories")
    s3.add_argument("--agent")
    s3.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.cmd == "store":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        mem_id = store_memory(
            text=args.text, agent=args.agent, memory_type=args.type,
            title=args.title, tags=tags, importance=args.importance,
            source_file=args.source, summary=args.summary
        )
        print(json.dumps({"id": mem_id, "status": "stored"}))

    elif args.cmd == "search":
        results = search_memories(args.query, agent=args.agent, topk=args.topk)
        print(json.dumps(results, indent=2))

    elif args.cmd == "list":
        results = list_memories(agent=args.agent, limit=args.limit)
        print(json.dumps(results, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
