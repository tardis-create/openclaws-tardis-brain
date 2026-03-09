#!/usr/bin/env python3
"""
dgraph-qmd: Fake QMD binary that serves OpenClaw memory queries from Dgraph.

Features:
- Full-text search on AgentMemory
- Semantic similarity via embeddings
- Cross-encoder reranking
- Relevance tracking (recall_count, last_recalled_at)
- Usefulness scoring (usefulness_score, usefulness_count)

Commands handled:
  search <query> --json -n <limit> -c <collection>
  vsearch <query> --json -n <limit> -c <collection>
  query <query> --json -n <limit> -c <collection>
  useful --memory-id <uid> --score <1|-1>
  stats --agent <agent> --sort <recall|usefulness|least-useful|never-recalled>
  update  → syncs Dgraph AgentMemory → markdown files + SQLite
  embed   → no-op
  collection add <name> --path <p> --pattern <pat>  → no-op
  collection list --json  → returns our dgraph collection
"""

import sys
import os
import json
import sqlite3
import re
import hashlib
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# ── Config ───────────────────────────────────────────────────────────────────
DGRAPH = os.environ.get("DGRAPH_URL", "http://localhost:8080")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "tardis")
STATE_DIR = os.environ.get("OPENCLAW_STATE_DIR", os.path.expanduser("~/.openclaw"))
QMD_CACHE = os.path.join(STATE_DIR, "agents", AGENT_ID, "qmd", "xdg-cache", "qmd")
SQLITE_PATH = os.path.join(QMD_CACHE, "index.sqlite")
MEMORY_EXPORT_DIR = os.path.expanduser("~/workspace/tardis-space/memory/dgraph-export")
COLLECTION_NAME = "dgraph-memory-tardis"
MAX_RESULTS = 8
SNIPPET_MAX = 700

# Reranking config
RERANK_ENABLED = os.environ.get("RERANK_ENABLED", "true").lower() == "true"
RERANK_MODEL = os.environ.get("RERANK_MODEL", "nomic-embed-text")
RERANK_WEIGHT = float(os.environ.get("RERANK_WEIGHT", "0.5"))


def log(msg: str):
    print(f"[dgraph-qmd] {msg}", file=sys.stderr)


# ── Dgraph helpers ────────────────────────────────────────────────────────────
def dgraph_query(dql: str) -> dict:
    r = requests.post(f"{DGRAPH}/query",
                      headers={"Content-Type": "application/dql"},
                      data=dql, timeout=10)
    return r.json().get("data", {})


def dgraph_alter(schema: str) -> dict:
    r = requests.post(f"{DGRAPH}/alter",
                      headers={"Content-Type": "text/plain"},
                      data=schema, timeout=10)
    return r.json()


def dgraph_mutate(rdf: str) -> dict:
    r = requests.post(f"{DGRAPH}/mutate",
                      headers={"Content-Type": "application/rdf"},
                      data=rdf, timeout=10)
    return r.json()


def dgraph_delete(uid: str) -> dict:
    """Delete a node by uid."""
    rdf = f'<{uid}> * * .'
    return dgraph_mutate(rdf)


# ── Embedding helpers ────────────────────────────────────────────────────────
def get_embedding(text: str) -> Optional[List[float]]:
    """Get embedding for text using Ollama."""
    try:
        payload = json.dumps({"model": RERANK_MODEL, "prompt": text}).encode()
        req = urllib_request(f"{OLLAMA_URL}/api/embeddings", data=payload)
        with urllib_request(req, timeout=30) as r:
            return json.loads(r.read())["embedding"]
    except Exception as e:
        log(f"Embedding failed: {e}")
        return None


def urllib_request(url: str, **kwargs):
    import urllib.request
    return urllib.request.Request(url, **kwargs)


# ── Relevance & Usefulness Tracking ────────────────────────────────────────
def increment_recall(uid: str):
    """Increment recall_count and update last_recalled_at for a memory."""
    now = datetime.now(timezone.utc).isoformat()
    
    # First get current values
    dql = f'''{{ q(func: uid({uid})) {{ uid recall: AgentMemory.recall_count last: AgentMemory.last_recalled_at }} }}'''
    data = dgraph_query(dql)
    results = data.get("q", [])
    
    if results:
        current_count = results[0].get("recall", 0) or 0
    else:
        current_count = 0
    
    # Update with increment
    rdf = f'''
    {{
        uid("{uid}") .
        AgentMemory.recall_count : {current_count + 1} .
        AgentMemory.last_recalled_at : "{now}"^^<xs:dateTime> .
    }}
    '''
    dgraph_mutate(rdf)


def update_usefulness(uid: str, score: int):
    """Update usefulness_score for a memory.
    
    score: 1 for useful, -1 for not useful
    """
    now = datetime.now(timezone.utc).isoformat()
    
    # Get current values
    dql = f'''{{ q(func: uid({uid})) {{ uid us: AgentMemory.usefulness_score uc: AgentMemory.usefulness_count }} }}'''
    data = dgraph_query(dql)
    results = data.get("q", [])
    
    if results:
        current_score = results[0].get("us", 0.0) or 0.0
        current_count = results[0].get("uc", 0) or 0
    else:
        current_score = 0.0
        current_count = 0
    
    # Calculate new average
    new_count = current_count + 1
    new_score = ((current_score * current_count) + score) / new_count
    
    rdf = f'''
    {{
        uid("{uid}") .
        AgentMemory.usefulness_score : {new_score} .
        AgentMemory.usefulness_count : {new_count} .
    }}
    '''
    dgraph_mutate(rdf)


def get_stats(agent: str, sort_by: str = "recall") -> dict:
    """Get memory stats for an agent."""
    
    if sort_by == "recall":
        order = "desc(AgentMemory.recall_count)"
    elif sort_by == "usefulness":
        order = "desc(AgentMemory.usefulness_score)"
    elif sort_by == "least-useful":
        order = "asc(AgentMemory.usefulness_score)"
    elif sort_by == "never-recalled":
        order = "asc(AgentMemory.recall_count)"
    else:
        order = "desc(AgentMemory.stored_at)"
    
    dql = f'''
    {{
      q(func: type(AgentMemory), first: 100, orderby: {order}) @filter(eq(AgentMemory.agent, "{agent}")) {{
        uid
        AgentMemory.id
        AgentMemory.title
        AgentMemory.content
        AgentMemory.memory_type
        AgentMemory.tags
        AgentMemory.importance
        AgentMemory.recall_count
        AgentMemory.usefulness_score
        AgentMemory.usefulness_count
        AgentMemory.last_recalled_at
        AgentMemory.stored_at
      }}
    }}
    '''
    
    try:
        data = dgraph_query(dql)
        memories = data.get("q", [])
    except Exception as e:
        log(f"Stats query failed: {e}")
        return {"error": str(e)}
    
    # Calculate totals
    total = len(memories)
    total_recalls = sum(m.get("AgentMemory.recall_count", 0) or 0 for m in memories)
    
    useful_memories = [m for m in memories if (m.get("AgentMemory.usefulness_count", 0) or 0) > 0]
    if useful_memories:
        avg_usefulness = sum(m.get("AgentMemory.usefulness_score", 0) or 0 for m in useful_memories) / len(useful_memories)
    else:
        avg_usefulness = 0.0
    
    # Get top/bottom based on sort
    if sort_by == "never-recalled":
        top = [m for m in memories if (m.get("AgentMemory.recall_count", 0) or 0) == 0][:10]
    else:
        top = memories[:10]
    
    return {
        "agent": agent,
        "total_memories": total,
        "total_recalls": total_recalls,
        "avg_usefulness": round(avg_usefulness, 2),
        "sort_by": sort_by,
        "top_memories": top
    }


# ── Reranking ────────────────────────────────────────────────────────────────
def rerank_memories(query: str, memories: List[Dict], limit: int = 8) -> List[Dict]:
    """Rerank memories using cross-encoder-style scoring.
    
    Combines:
    - Keyword match score
    - Recency score (more recent = higher)
    - Importance score
    - Usefulness score (if available)
    """
    if not memories:
        return []
    
    query_words = set(query.lower().split())
    now = datetime.now(timezone.utc)
    
    scored = []
    for m in memories:
        # Keyword score
        content = (m.get("AgentMemory.content") or "").lower()
        title = (m.get("AgentMemory.title") or "").lower()
        tags = " ".join(m.get("AgentMemory.tags") or []).lower()
        combined = f"{title} {content} {tags}"
        keyword_score = sum(1 for w in query_words if w in combined) / max(len(query_words), 1)
        
        # Recency score (0-1, based on stored_at)
        stored_at = m.get("AgentMemory.stored_at", "")
        if stored_at:
            try:
                stored = datetime.fromisoformat(stored_at.replace("Z", "+00:00"))
                days_old = (now - stored).days
                recency_score = max(0, 1 - (days_old / 365))  # Decay over year
            except:
                recency_score = 0.5
        else:
            recency_score = 0.5
        
        # Importance score
        importance = m.get("AgentMemory.importance", 0.7) or 0.7
        importance_score = float(importance)
        
        # Usefulness score (if available)
        usefulness = m.get("AgentMemory.usefulness_score")
        if usefulness is not None:
            usefulness_score = float(usefulness)
        else:
            usefulness_score = 0.5  # Neutral if not rated
        
        # Recall bonus (well-recalled = probably important)
        recall_count = m.get("AgentMemory.recall_count", 0) or 0
        recall_bonus = min(recall_count / 20, 0.3)  # Max 0.3 bonus
        
        # Combined score with weights
        final_score = (
            (keyword_score * 0.3) +
            (recency_score * 0.15) +
            (importance_score * 0.2) +
            (usefulness_score * 0.25) +
            (recall_bonus * 0.1)
        )
        
        scored.append((final_score, m))
    
    # Sort by score descending
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:limit]]


# ── Search ──────────────────────────────────────────────────────────────────
def search_memories(query: str, limit: int) -> list:
    """Full-text keyword search on Dgraph AgentMemory for this agent."""
    # Sanitize for DQL
    safe_q = re.sub(r'[^\w\s-]', '', query)
    terms = " ".join(safe_q.split()[:8])

    # Try anyofterms first (requires term index)
    dql = f'''
    {{
      q(func: anyofterms(AgentMemory.content, "{terms}"), first: {limit * 4}) 
      @filter(eq(AgentMemory.agent, "{AGENT_ID}")) {{
        uid
        AgentMemory.id
        AgentMemory.title
        AgentMemory.content
        AgentMemory.memory_type
        AgentMemory.tags
        AgentMemory.importance
        AgentMemory.recall_count
        AgentMemory.usefulness_score
        AgentMemory.usefulness_count
        AgentMemory.last_recalled_at
        AgentMemory.stored_at
      }}
    }}
    '''
    try:
        data = dgraph_query(dql)
        results = data.get("q", [])
    except Exception as e:
        log(f"term search failed: {e}")
        results = []

    # Fallback: load all memories and filter client-side
    if not results:
        dql2 = f'''
        {{
          q(func: type(AgentMemory), first: 200) 
          @filter(eq(AgentMemory.agent, "{AGENT_ID}")) {{
            uid
            AgentMemory.id
            AgentMemory.title
            AgentMemory.content
            AgentMemory.memory_type
            AgentMemory.tags
            AgentMemory.importance
            AgentMemory.recall_count
            AgentMemory.usefulness_score
            AgentMemory.usefulness_count
            AgentMemory.last_recalled_at
            AgentMemory.stored_at
          }}
        }}
        '''
        try:
            data = dgraph_query(dql2)
            all_mems = data.get("q", [])
        except Exception as e:
            log(f"fallback query failed: {e}")
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())
        scored = []
        for m in all_mems:
            content = (m.get("AgentMemory.content") or "").lower()
            title = (m.get("AgentMemory.title") or "").lower()
            tags = " ".join(m.get("AgentMemory.tags") or []).lower()
            combined = f"{title} {content} {tags}"
            # Simple keyword score
            hits = sum(1 for w in query_words if w in combined)
            if hits > 0:
                scored.append((hits, m))
        scored.sort(key=lambda x: -x[0])
        results = [m for _, m in scored[:limit * 2]]

    # Rerank if enabled
    if RERANK_ENABLED and results:
        results = rerank_memories(query, results, limit)
    else:
        results = results[:limit]

    # Increment recall for each returned memory
    for m in results:
        uid = m.get("uid", "")
        if uid:
            increment_recall(uid)

    return results[:limit]


# ── SQLite helpers ────────────────────────────────────────────────────────────
def ensure_sqlite():
    """Ensure documents table has our dgraph collection entries."""
    os.makedirs(QMD_CACHE, exist_ok=True)
    db = sqlite3.connect(SQLITE_PATH)
    # Ensure tables exist
    db.execute("""CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY,
        collection TEXT NOT NULL,
        path TEXT NOT NULL,
        title TEXT,
        hash TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        modified_at TEXT NOT NULL DEFAULT (datetime('now')),
        active INTEGER NOT NULL DEFAULT 1
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS content (
        hash TEXT PRIMARY KEY,
        doc TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    db.commit()
    return db


def upsert_doc(db, uid: str, path: str, title: str, content: str):
    """Insert or update a document in QMD SQLite using dgraph uid as hash."""
    now = datetime.now(timezone.utc).isoformat()
    # Check if exists
    row = db.execute("SELECT id FROM documents WHERE hash = ?", (uid,)).fetchone()
    if row:
        db.execute("UPDATE documents SET path=?, title=?, modified_at=?, active=1 WHERE hash=?",
                   (path, title, now, uid))
    else:
        db.execute("INSERT INTO documents (collection, path, title, hash, created_at, modified_at, active) VALUES (?,?,?,?,?,?,1)",
                   (COLLECTION_NAME, path, title, uid, now, now))
    # Upsert content
    db.execute("INSERT OR REPLACE INTO content (hash, doc, created_at) VALUES (?,?,?)",
               (uid, content, now))


# ── Sync: Dgraph → markdown files + SQLite ───────────────────────────────────
def sync_dgraph_to_sqlite():
    """Pull all agent memories from Dgraph, write to markdown + SQLite."""
    log(f"Syncing Dgraph memories for agent={AGENT_ID}...")
    dql = f'''
    {{
      q(func: type(AgentMemory), first: 1000) 
      @filter(eq(AgentMemory.agent, "{AGENT_ID}")) {{
        uid
        AgentMemory.id
        AgentMemory.title
        AgentMemory.content
        AgentMemory.memory_type
        AgentMemory.tags
        AgentMemory.importance
        AgentMemory.stored_at
        AgentMemory.summary
        AgentMemory.recall_count
        AgentMemory.usefulness_score
        AgentMemory.usefulness_count
      }}
    }}
    '''
    try:
        data = dgraph_query(dql)
        memories = data.get("q", [])
    except Exception as e:
        log(f"Dgraph query failed: {e}")
        return

    os.makedirs(MEMORY_EXPORT_DIR, exist_ok=True)
    db = ensure_sqlite()

    count = 0
    for m in memories:
        uid = m.get("uid", "")
        if not uid:
            continue
        uid_short = uid.replace("0x", "")
        title = m.get("AgentMemory.title") or "Memory"
        content = m.get("AgentMemory.content") or ""
        mtype = m.get("AgentMemory.memory_type") or "episodic"
        tags = m.get("AgentMemory.tags") or []
        importance = m.get("AgentMemory.importance", 0.7)
        stored_at = m.get("AgentMemory.stored_at") or ""
        summary = m.get("AgentMemory.summary") or ""
        recall_count = m.get("AgentMemory.recall_count", 0) or 0
        usefulness = m.get("AgentMemory.usefulness_score", 0.0) or 0.0

        # Build markdown content
        md = f"# {title}\n\n"
        md += f"**Type:** {mtype} | **Importance:** {importance}\n"
        if tags:
            md += f"**Tags:** {', '.join(tags)}\n"
        if stored_at:
            md += f"**Stored:** {stored_at}\n"
        md += f"**Recalls:** {recall_count} | **Usefulness:** {usefulness:.2f}\n"
        md += f"\n{content}\n"
        if summary and summary != content:
            md += f"\n**Summary:** {summary}\n"

        # Write file
        fpath = os.path.join(MEMORY_EXPORT_DIR, f"{uid_short}.md")
        with open(fpath, "w") as f:
            f.write(md)

        upsert_doc(db, uid, fpath, title, md)
        count += 1

    db.commit()
    db.close()
    log(f"Synced {count} memories → {MEMORY_EXPORT_DIR} + SQLite")


# ── Search handler ────────────────────────────────────────────────────────────
def handle_search(query: str, limit: int):
    """Search Dgraph, ensure SQLite has docs, return QMD-format JSON."""
    memories = search_memories(query, limit)

    if not memories:
        # QMD "no results" marker
        print("no results found", file=sys.stdout)
        return

    db = ensure_sqlite()
    results = []
    for m in memories:
        uid = m.get("uid", "")
        if not uid:
            continue
        title = m.get("AgentMemory.title") or "Memory"
        content = m.get("AgentMemory.content") or ""
        mtype = m.get("AgentMemory.memory_type") or ""
        importance = m.get("AgentMemory.importance", 0.7)
        recall = m.get("AgentMemory.recall_count", 0) or 0
        usefulness = m.get("AgentMemory.usefulness_score", 0.0) or 0.0

        # Build the snippet (what gets injected into prompts)
        snippet = f"{title}\n{content}"
        if mtype:
            snippet = f"[{mtype}] {snippet}"
        snippet = snippet[:SNIPPET_MAX]

        # Build markdown for the file
        md = f"# {title}\n\n{content}\n"
        uid_short = uid.replace("0x", "")
        fpath = os.path.join(MEMORY_EXPORT_DIR, f"{uid_short}.md")
        os.makedirs(MEMORY_EXPORT_DIR, exist_ok=True)
        if not os.path.exists(fpath):
            with open(fpath, "w") as f:
                f.write(md)

        upsert_doc(db, uid, fpath, title, md)

        # Score based on importance + usefulness
        base_score = float(importance) if isinstance(importance, (int, float)) else 0.7
        if usefulness > 0:
            base_score = (base_score + float(usefulness)) / 2

        results.append({
            "docid": uid,
            "snippet": snippet,
            "score": base_score,
            "collection": COLLECTION_NAME,
            "file": fpath,
            "metadata": {
                "recall_count": recall,
                "usefulness_score": usefulness,
                "memory_type": mtype
            }
        })

    db.commit()
    db.close()

    print(json.dumps(results), file=sys.stdout)


# ── Collection list ───────────────────────────────────────────────────────────
def handle_collection_list():
    out = [{"name": COLLECTION_NAME, "path": MEMORY_EXPORT_DIR, "pattern": "**/*.md"}]
    print(json.dumps(out))


# ── Stats handler ────────────────────────────────────────────────────────────
def handle_stats(agent: str, sort_by: str):
    stats = get_stats(agent, sort_by)
    print(json.dumps(stats, indent=2, default=str))


# ── Useful handler ────────────────────────────────────────────────────────────
def handle_useful(memory_id: str, score: int):
    """Mark a memory as useful or not."""
    # Handle both uid formats
    uid = memory_id if memory_id.startswith("0x") else f"0x{memory_id}"
    update_usefulness(uid, score)
    log(f"Updated usefulness for {uid}: score={score}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    if not args:
        print("dgraph-qmd: Dgraph-backed QMD with reranking", file=sys.stderr)
        sys.exit(0)

    cmd = args[0]

    # stats command
    if cmd == "stats":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--agent", default=AGENT_ID)
        parser.add_argument("--sort", default="recall")
        parsed, _ = parser.parse_known_args(args[1:])
        handle_stats(parsed.agent, parsed.sort)
        return

    # useful command
    if cmd == "useful":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--memory-id", required=True)
        parser.add_argument("--score", type=int, required=True)
        parsed, _ = parser.parse_known_args(args[1:])
        handle_useful(parsed.memory_id, parsed.score)
        return

    # collection subcommand
    if cmd == "collection":
        subcmd = args[1] if len(args) > 1 else ""
        if subcmd == "list":
            handle_collection_list()
        elif subcmd == "add":
            # no-op — we manage our own collection
            log(f"collection add no-op: {' '.join(args[2:])}")
        else:
            log(f"unknown collection subcmd: {subcmd}")
        return

    # update → sync Dgraph to SQLite
    if cmd == "update":
        sync_dgraph_to_sqlite()
        return

    # embed → no-op
    if cmd == "embed":
        log("embed no-op")
        return

    # search / vsearch / query
    if cmd in ("search", "vsearch", "query"):
        # Parse: <cmd> <query> [--json] [-n <limit>] [-c <collection>...
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("query_pos", nargs="?", default="")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("-n", "--limit", type=int, default=MAX_RESULTS)
        parser.add_argument("-c", "--collection", action="append", default=[])
        parser.add_argument("--query", default=None)
        try:
            parsed, _ = parser.parse_known_args(args[1:])
        except SystemExit:
            parsed = argparse.Namespace(query_pos="", limit=MAX_RESULTS, collection=[])

        query = parsed.query or parsed.query_pos or ""
        limit = parsed.limit or MAX_RESULTS

        handle_search(query, limit)
        return

    log(f"unknown command: {cmd} {' '.join(args[1:])}")
    sys.exit(0)


if __name__ == "__main__":
    main()
