#!/usr/bin/env python3
"""
dgraph-qmd: Fake QMD binary that serves OpenClaw memory queries from Dgraph.

Commands handled:
  search <query> --json -n <limit> -c <collection>
  vsearch <query> --json -n <limit> -c <collection>
  query <query> --json -n <limit> -c <collection>
  update  → syncs Dgraph AgentMemory → markdown files + SQLite
  embed   → no-op
  collection add <name> --path <p> --pattern <pat>  → no-op
  collection list --json  → returns our dgraph collection

Output format expected by OpenClaw:
  JSON array of: {docid, snippet, score, collection, file}
  docid must match `documents.hash` in QMD SQLite
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

# ── Config ───────────────────────────────────────────────────────────────────
DGRAPH = "http://localhost:8080"
AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "tardis")
STATE_DIR = os.environ.get("OPENCLAW_STATE_DIR", os.path.expanduser("~/.openclaw"))
QMD_CACHE = os.path.join(STATE_DIR, "agents", AGENT_ID, "qmd", "xdg-cache", "qmd")
SQLITE_PATH = os.path.join(QMD_CACHE, "index.sqlite")
MEMORY_EXPORT_DIR = os.path.expanduser("~/workspace/tardis-space/memory/dgraph-export")
COLLECTION_NAME = "dgraph-memory-tardis"
MAX_RESULTS = 8
SNIPPET_MAX = 700


def log(msg):
    print(f"[dgraph-qmd] {msg}", file=sys.stderr)


# ── Dgraph helpers ────────────────────────────────────────────────────────────
def dgraph_query(dql: str) -> dict:
    r = requests.post(f"{DGRAPH}/query",
                      headers={"Content-Type": "application/dql"},
                      data=dql, timeout=10)
    return r.json().get("data", {})


def search_memories(query: str, limit: int) -> list:
    """Full-text keyword search on Dgraph AgentMemory for this agent."""
    # Sanitize for DQL
    safe_q = re.sub(r'[^\w\s-]', '', query)
    terms = " ".join(safe_q.split()[:8])

    # Try anyofterms first (requires term index)
    dql = f'''{{
      q(func: anyofterms(AgentMemory.content, "{terms}"), first: {limit * 3}) @filter(eq(AgentMemory.agent, "{AGENT_ID}")) {{
        uid
        AgentMemory.id
        AgentMemory.title
        AgentMemory.content
        AgentMemory.memory_type
        AgentMemory.tags
        AgentMemory.importance
        AgentMemory.stored_at
      }}
    }}'''
    try:
        data = dgraph_query(dql)
        results = data.get("q", [])
    except Exception as e:
        log(f"term search failed: {e}")
        results = []

    # Fallback: load all memories and filter client-side
    if not results:
        dql2 = f'''{{
          q(func: type(AgentMemory), first: 200) @filter(eq(AgentMemory.agent, "{AGENT_ID}")) {{
            uid
            AgentMemory.id
            AgentMemory.title
            AgentMemory.content
            AgentMemory.memory_type
            AgentMemory.tags
            AgentMemory.importance
            AgentMemory.stored_at
          }}
        }}'''
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
    dql = f'''{{
      q(func: type(AgentMemory), first: 1000) @filter(eq(AgentMemory.agent, "{AGENT_ID}")) {{
        uid
        AgentMemory.id
        AgentMemory.title
        AgentMemory.content
        AgentMemory.memory_type
        AgentMemory.tags
        AgentMemory.importance
        AgentMemory.stored_at
        AgentMemory.summary
      }}
    }}'''
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

        # Build markdown content
        md = f"# {title}\n\n"
        md += f"**Type:** {mtype} | **Importance:** {importance}\n"
        if tags:
            md += f"**Tags:** {', '.join(tags)}\n"
        if stored_at:
            md += f"**Stored:** {stored_at}\n"
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

        # Score based on importance
        score = float(importance) if isinstance(importance, (int, float)) else 0.7

        results.append({
            "docid": uid,
            "snippet": snippet,
            "score": score,
            "collection": COLLECTION_NAME,
            "file": fpath,
        })

    db.commit()
    db.close()

    print(json.dumps(results), file=sys.stdout)


# ── Collection list ───────────────────────────────────────────────────────────
def handle_collection_list():
    out = [{"name": COLLECTION_NAME, "path": MEMORY_EXPORT_DIR, "pattern": "**/*.md"}]
    print(json.dumps(out))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    if not args:
        print("dgraph-qmd: Dgraph-backed QMD replacement", file=sys.stderr)
        sys.exit(0)

    cmd = args[0]

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
        # Parse: <cmd> <query> [--json] [-n <limit>] [-c <collection>...]
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
