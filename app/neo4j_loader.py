"""Push GraphRAG output (entities + relationships) into Neo4j and open Neo4j Browser."""
from __future__ import annotations

import os
import re
import webbrowser

import pandas as pd

from .project import GraphRAGProject


_DEFAULT_URI = "bolt://localhost:7687"
_DEFAULT_USER = "neo4j"
_BROWSER_URL = "http://localhost:7474/browser/"


def _load_env_from_project(project: GraphRAGProject) -> None:
    if not project.env_path.exists():
        return
    for raw in project.env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _sanitize_label(s: str) -> str:
    if not s:
        return "Unknown"
    cleaned = re.sub(r"\W", "_", s.strip(), flags=re.UNICODE)
    return cleaned or "Unknown"


def push_to_neo4j(project: GraphRAGProject, *, wipe: bool = True) -> tuple[bool, str]:
    """Push the project's graph into Neo4j and open Neo4j Browser. Returns (ok, message)."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return False, (
            "Python package 'neo4j' is not installed.\n"
            "Run: uv pip install neo4j  (or: pip install neo4j)"
        )

    _load_env_from_project(project)
    uri = os.environ.get("NEO4J_URI", _DEFAULT_URI)
    user = os.environ.get("NEO4J_USER", _DEFAULT_USER)
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        return False, (
            "NEO4J_PASSWORD missing. Add the following to this project's .env "
            "(Projects tab → .env editor):\n\n"
            f"NEO4J_URI={_DEFAULT_URI}\n"
            f"NEO4J_USER={_DEFAULT_USER}\n"
            "NEO4J_PASSWORD=<the password you set in Neo4j Desktop>"
        )

    entities_path = project.output_dir / "entities.parquet"
    relationships_path = project.output_dir / "relationships.parquet"
    if not entities_path.exists() or not relationships_path.exists():
        return False, "entities.parquet / relationships.parquet missing — run indexing first."

    entities = pd.read_parquet(entities_path)
    relationships = pd.read_parquet(relationships_path)

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
    except Exception as exc:
        return False, (
            f"Could not connect to Neo4j at {uri}.\n"
            "Make sure Neo4j Desktop is running and the DBMS is started.\n\n"
            f"Error: {exc}"
        )

    try:
        with driver.session() as session:
            if wipe:
                session.run("MATCH (n) DETACH DELETE n")

            entity_rows = [
                {
                    "id": str(r["id"]),
                    "title": str(r.get("title") or ""),
                    "type_raw": str(r.get("type") or "Unknown"),
                    "type_label": _sanitize_label(str(r.get("type") or "Unknown")),
                    "description": str(r.get("description") or ""),
                    "frequency": int(r.get("frequency") or 0),
                    "degree": int(r.get("degree") or 0),
                }
                for _, r in entities.iterrows()
            ]

            for row in entity_rows:
                session.run(
                    f"MERGE (n:Entity:`{row['type_label']}` {{id: $id}}) "
                    "SET n.title = $title, n.type = $type_raw, "
                    "    n.description = $description, n.frequency = $frequency, n.degree = $degree",
                    **row,
                )

            for _, r in relationships.iterrows():
                session.run(
                    "MATCH (s:Entity {title: $source}), (t:Entity {title: $target}) "
                    "MERGE (s)-[rel:RELATED {id: $id}]->(t) "
                    "SET rel.description = $description, rel.weight = $weight",
                    id=str(r["id"]),
                    source=str(r.get("source") or ""),
                    target=str(r.get("target") or ""),
                    description=str(r.get("description") or ""),
                    weight=float(r.get("weight") or 1.0),
                )

            n_nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            n_rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    except Exception as exc:
        driver.close()
        return False, f"Failed during Neo4j upsert: {exc}"

    driver.close()

    try:
        webbrowser.open(_BROWSER_URL)
    except Exception:
        pass

    return True, (
        f"Loaded {n_nodes} nodes and {n_rels} relationships into {uri}.\n"
        f"Opened {_BROWSER_URL} — try: MATCH (n)-[r]-(m) RETURN n,r,m LIMIT 200"
    )
