#!/usr/bin/env python3
"""
brain_query.py — Knowledge Graph Query Tool

Query the Dgraph knowledge graph for:
- People (contacts, roles, relationships)
- Projects (status, team, domain)
- SOPs (procedures, how-tos)
- Insights (learnings, decisions)

Also handles agent memory search via AgentMemory nodes.
"""

import argparse
import json
import os
import sys
import requests
import re

# ── Config ───────────────────────────────────────────────────────────────────
DGRAPH = os.environ.get("DGRAPH_URL", "http://localhost:8080")
AGENT = os.environ.get("OPENCLAW_AGENT_ID", "tardis")


def dgraph_query(dql: str) -> dict:
    r = requests.post(
        f"{DGRAPH}/query",
        headers={"Content-Type": "application/dql"},
        data=dql,
        timeout=15
    )
    return r.json().get("data", {})


def dgraph_mutate(mutation: str) -> dict:
    r = requests.post(
        f"{DGRAPH}/mutate",
        headers={"Content-Type": "application/rdf"},
        data=mutation,
        timeout=15
    )
    return r.json()


# ── Knowledge Graph Queries ─────────────────────────────────────────────────
def query_persons(query: str = None) -> list:
    """Search persons by name, role, or context."""
    if query:
        safe = re.sub(r'[^\w\s-]', '', query)
        dql = f'''{{
            q(func: anyofterms(Person.name, "{safe}"), first: 10) {{
                uid
                Person.id
                Person.name
                Person.role
                Person.phone
                Person.email
                Person.context
                Person.tags
            }}
        }}'''
    else:
        dql = '''{ q(func: type(Person), first: 50) { uid Person.id Person.name Person.role Person.phone } }'''

    data = dgraph_query(dql)
    return data.get("q", [])


def query_projects(query: str = None) -> list:
    """Search projects by name, domain, or status."""
    if query:
        safe = re.sub(r'[^\w\s-]', '', query)
        dql = f'''{{
            q(func: anyofterms(Project.name, "{safe}"), first: 10) {{
                uid
                Project.id
                Project.name
                Project.description
                Project.status
                Project.domain
            }}
        }}'''
    else:
        dql = '''{ q(func: type(Project), first: 50) { uid Project.id Project.name Project.status } }'''

    data = dgraph_query(dql)
    return data.get("q", [])


def query_sops(query: str = None) -> list:
    """Search SOPs by title, domain, or content."""
    if query:
        safe = re.sub(r'[^\w\s-]', '', query)
        dql = f'''{{
            q(func: anyofterms(SOP.title, "{safe}"), first: 10) {{
                uid
                SOP.id
                SOP.title
                SOP.content
                SOP.domain
                SOP.tags
            }}
        }}'''
    else:
        dql = '''{ q(func: type(SOP), first: 50) { uid SOP.id SOP.title SOP.domain } }'''

    data = dgraph_query(dql)
    return data.get("q", [])


def query_insights(query: str = None) -> list:
    """Search insights by title, domain, or content."""
    if query:
        safe = re.sub(r'[^\w\s-]', '', query)
        dql = f'''{{
            q(func: anyofterms(Insight.title, "{safe}"), first: 10) {{
                uid
                Insight.id
                Insight.title
                Insight.content
                Insight.domain
                Insight.tags
            }}
        }}'''
    else:
        dql = '''{ q(func: type(Insight), first: 50) { uid Insight.id Insight.title Insight.domain } }'''

    data = dgraph_query(dql)
    return data.get("q", [])


# ── Memory Search ────────────────────────────────────────────────────────────
def search_memories(agent: str, query: str, limit: int = 5) -> list:
    """Full-text search on agent memories."""
    safe_q = re.sub(r'[^\w\s-]', '', query)
    terms = " ".join(safe_q.split()[:8])

    dql = f'''{{
        q(func: anyofterms(AgentMemory.content, "{terms}"), first: {limit * 2})
        @filter(eq(AgentMemory.agent, "{agent}")) {{
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
        return results[:limit]
    except Exception as e:
        print(f"Search error: {e}", file=sys.stderr)
        return []


# ── Mutations ────────────────────────────────────────────────────────────────
def add_person(id: str, name: str, role: str = None, phone: str = None,
               email: str = None, context: str = None, tags: list = None):
    """Add a person node to the knowledge graph."""
    tags_str = ",".join(f'"{t}"' for t in (tags or []))
    rdf = f'''
        {{
            "uid": "_:{id}",
            "Person.id": "{id}",
            "Person.name": "{name}",
            "Person.role": "{role or ''}",
            "Person.phone": "{phone or ''}",
            "Person.email": "{email or ''}",
            "Person.context": "{context or ''}",
            "Person.tags": [{tags_str}]
        }}
    '''
    result = dgraph_mutate(rdf)
    print(f"Added person: {name} (uid: {result.get('uids', {}).get(id, 'unknown')})")
    return result


def add_project(id: str, name: str, description: str = None,
                status: str = "active", domain: str = None):
    """Add a project node."""
    rdf = f'''
        {{
            "uid": "_:{id}",
            "Project.id": "{id}",
            "Project.name": "{name}",
            "Project.description": "{description or ''}",
            "Project.status": "{status}",
            "Project.domain": "{domain or ''}"
        }}
    '''
    result = dgraph_mutate(rdf)
    print(f"Added project: {name}")
    return result


def add_sop(id: str, title: str, content: str = None, domain: str = None, tags: list = None):
    """Add an SOP node."""
    tags_str = ",".join(f'"{t}"' for t in (tags or []))
    rdf = f'''
        {{
            "uid": "_:{id}",
            "SOP.id": "{id}",
            "SOP.title": "{title}",
            "SOP.content": "{content or ''}",
            "SOP.domain": "{domain or ''}",
            "SOP.tags": [{tags_str}]
        }}
    '''
    result = dgraph_mutate(rdf)
    print(f"Added SOP: {title}")
    return result


def add_insight(id: str, title: str, content: str = None, domain: str = None, tags: list = None):
    """Add an insight node."""
    tags_str = ",".join(f'"{t}"' for t in (tags or []))
    rdf = f'''
        {{
            "uid": "_:{id}",
            "Insight.id": "{id}",
            "Insight.title": "{title}",
            "Insight.content": "{content or ''}",
            "Insight.domain": "{domain or ''}",
            "Insight.tags": [{tags_str}]
        }}
    '''
    result = dgraph_mutate(rdf)
    print(f"Added insight: {title}")
    return result


def link_nodes(type: str, **kwargs):
    """Link two nodes (person-project, person-sop, etc.)."""
    if type == "person-project":
        rdf = f'''
            {{
                "uid": "{kwargs['person_uid']}",
                "Person.projects": {{ "uid": "{kwargs['project_uid']}" }}
            }}
        '''
    elif type == "person-sop":
        rdf = f'''
            {{
                "uid": "{kwargs['person_uid']}",
                "Person.sops": {{ "uid": "{kwargs['sop_uid']}" }}
            }}
        '''
    else:
        print(f"Unknown link type: {type}")
        return

    result = dgraph_mutate(rdf)
    print(f"Linked nodes: {type}")
    return result


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Brain Query Tool")
    sub = parser.add_subparsers(dest="action", help="Action to perform")

    # Search
    sub.add_argument("query", nargs="?", help="Search query")
    sub.add_argument("--agent", default=AGENT, help="Agent ID for memory search")
    sub.add_argument("--limit", type=int, default=5, help="Max results")

    # Add commands
    add_p = sub.add_parser("add-person", help="Add a person")
    add_p.add_argument("--id", required=True)
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--role")
    add_p.add_argument("--phone")
    add_p.add_argument("--email")
    add_p.add_argument("--context")
    add_p.add_argument("--tags", help="comma-separated")

    add_proj = sub.add_parser("add-project", help="Add a project")
    add_proj.add_argument("--id", required=True)
    add_proj.add_argument("--name", required=True)
    add_proj.add_argument("--description")
    add_proj.add_argument("--status", default="active")
    add_proj.add_argument("--domain")

    add_sop = sub.add_parser("add-sop", help="Add an SOP")
    add_sop.add_argument("--id", required=True)
    add_sop.add_argument("--title", required=True)
    add_sop.add_argument("--content")
    add_sop.add_argument("--domain")
    add_sop.add_argument("--tags", help="comma-separated")

    add_ins = sub.add_parser("add-insight", help="Add an insight")
    add_ins.add_argument("--id", required=True)
    add_ins.add_argument("--title", required=True)
    add_ins.add_argument("--content")
    add_ins.add_argument("--domain")
    add_ins.add_argument("--tags", help="comma-separated")

    # List
    list_p = sub.add_parser("list", help="List nodes")
    list_p.add_argument("--type", choices=["people", "projects", "sops", "insights"], required=True)

    # Test
    sub.add_parser("test", help="Test Dgraph connection")

    args = parser.parse_args()

    # Test connection
    if args.action == "test":
        try:
            r = requests.get(f"{DGRAPH}/health", timeout=5)
            if r.status_code == 200:
                print("✓ Dgraph connected")
                # Count nodes
                dql = '{ count(func: type(AgentMemory)) }'
                data = dgraph_query(dql)
                print(f"  AgentMemory nodes: {data.get('count', '?')}")
                dql = '{ count(func: type(Person)) }'
                data = dgraph_query(dql)
                print(f"  Person nodes: {data.get('count', '?')}")
            else:
                print(f"✗ Dgraph returned {r.status_code}")
        except Exception as e:
            print(f"✗ Connection failed: {e}")
        return

    # List
    if args.action == "list":
        if args.type == "people":
            print(json.dumps(query_persons(), indent=2))
        elif args.type == "projects":
            print(json.dumps(query_projects(), indent=2))
        elif args.type == "sops":
            print(json.dumps(query_sops(), indent=2))
        elif args.type == "insights":
            print(json.dumps(query_insights(), indent=2))
        return

    # Add commands
    if args.action == "add-person":
        tags = args.tags.split(",") if args.tags else None
        add_person(args.id, args.name, args.role, args.phone, args.email, args.context, tags)
        return

    if args.action == "add-project":
        add_project(args.id, args.name, args.description, args.status, args.domain)
        return

    if args.action == "add-sop":
        tags = args.tags.split(",") if args.tags else None
        add_sop(args.id, args.title, args.content, args.domain, tags)
        return

    if args.action == "add-insight":
        tags = args.tags.split(",") if args.tags else None
        add_insight(args.id, args.title, args.content, args.domain, tags)
        return

    # Search (default action)
    if args.query:
        print(f"Searching memories for: {args.query}", file=sys.stderr)
        results = search_memories(args.agent, args.query, args.limit)
        if results:
            print(json.dumps(results, indent=2))
        else:
            print("No results found.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
