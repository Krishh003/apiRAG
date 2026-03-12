"""
Graph Store — Neo4j for API relationship traversal.

Stores API nodes and typed relationships:
  REQUIRES  — must call X before Y (e.g. Create PI before Confirm PI)
  TRIGGERS  — calling X fires Y (e.g. Confirm PI triggers Stripe Webhook)
  PRECEDES  — X is typically followed by Y in a workflow
  BELONGS_TO — API belongs to Platform node
  IN_CATEGORY — API belongs to Category node

Used by planning_handler.py to find multi-hop API call sequences.
"""

import logging
from typing import List, Dict, Optional
from neo4j import GraphDatabase
from models import APIEntry

logger = logging.getLogger(__name__)


class GraphStore:

    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._init_schema()

    def close(self):
        self._driver.close()

    def _init_schema(self):
        """Create indexes and constraints on first run."""
        with self._driver.session() as session:
            session.run("""
                CREATE CONSTRAINT api_name_platform IF NOT EXISTS
                FOR (a:API) REQUIRE (a.name, a.platform) IS UNIQUE
            """)
            session.run("CREATE INDEX api_platform IF NOT EXISTS FOR (a:API) ON (a.platform)")
            session.run("CREATE INDEX api_category IF NOT EXISTS FOR (a:API) ON (a.category)")
            session.run("""
                CREATE CONSTRAINT platform_name IF NOT EXISTS
                FOR (p:Platform) REQUIRE p.name IS UNIQUE
            """)
        logger.info("Neo4j schema initialized")

    # ── Write ─────────────────────────────────────────────────────────────

    def upsert_entries(self, entries: List[APIEntry]):
        """
        Upsert API nodes and all their relationships.
        Uses MERGE to avoid duplicates.
        """
        with self._driver.session() as session:
            for entry in entries:
                # Upsert Platform node
                session.run(
                    "MERGE (p:Platform {name: $platform})",
                    platform=entry.platform,
                )

                # Upsert Category node
                session.run(
                    "MERGE (c:Category {name: $category})",
                    category=entry.category,
                )

                # Upsert API node
                session.run("""
                    MERGE (a:API {name: $name, platform: $platform})
                    SET a.category     = $category,
                        a.method       = $method,
                        a.endpoint     = $endpoint,
                        a.base_url     = $base_url,
                        a.description  = $description,
                        a.plain        = $plain,
                        a.doc_url      = $doc_url,
                        a.is_internal  = $is_internal
                """,
                    name=entry.name,
                    platform=entry.platform,
                    category=entry.category,
                    method=entry.method,
                    endpoint=entry.endpoint,
                    base_url=entry.base_url,
                    description=entry.description[:500],
                    plain=entry.plain_explanation[:500],
                    doc_url=entry.doc_url,
                    is_internal=entry.is_internal,
                )

                # Link to Platform
                session.run("""
                    MATCH (a:API {name: $name, platform: $platform})
                    MATCH (p:Platform {name: $platform})
                    MERGE (a)-[:BELONGS_TO]->(p)
                """, name=entry.name, platform=entry.platform)

                # Link to Category
                session.run("""
                    MATCH (a:API {name: $name, platform: $platform})
                    MATCH (c:Category {name: $category})
                    MERGE (a)-[:IN_CATEGORY]->(c)
                """, name=entry.name, platform=entry.platform, category=entry.category)

            # Create relationships in a second pass (all nodes must exist first)
            for entry in entries:
                self._upsert_relationships(session, entry)

        logger.info(f"Neo4j upserted {len(entries)} entries")

    def _upsert_relationships(self, session, entry: APIEntry):
        """Create typed relationships from an APIEntry's requires/triggers/precedes lists."""
        for rel_type, targets in [
            ("REQUIRES", entry.requires),
            ("TRIGGERS", entry.triggers),
            ("PRECEDES", entry.precedes),
        ]:
            for target_name in targets:
                if not target_name:
                    continue
                # Use MERGE with fuzzy name match (target API may be from same platform)
                session.run(f"""
                    MATCH (a:API {{name: $source_name, platform: $platform}})
                    MATCH (b:API) WHERE b.name CONTAINS $target_fragment OR $target_fragment CONTAINS b.name
                    MERGE (a)-[:{rel_type}]->(b)
                """,
                    source_name=entry.name,
                    platform=entry.platform,
                    target_fragment=target_name[:40],
                )

    # ── Read — Planning Queries ───────────────────────────────────────────

    def find_api_workflow(
        self,
        start_api_name: str,
        max_hops: int = 4,
    ) -> List[Dict]:
        """
        Starting from a named API, traverse PRECEDES + REQUIRES + TRIGGERS
        relationships to find the full workflow sequence.
        Returns ordered list of API nodes.
        """
        with self._driver.session() as session:
            result = session.run("""
                MATCH (start:API)
                WHERE start.name CONTAINS $name OR $name CONTAINS start.name
                CALL apoc.path.subgraphNodes(start, {
                    relationshipFilter: "PRECEDES>|REQUIRES>|TRIGGERS>",
                    maxLevel: $max_hops
                })
                YIELD node
                RETURN DISTINCT node.name AS name,
                               node.platform AS platform,
                               node.category AS category,
                               node.method AS method,
                               node.endpoint AS endpoint,
                               node.description AS description,
                               node.plain AS plain,
                               node.doc_url AS doc_url
                LIMIT 10
            """, name=start_api_name, max_hops=max_hops)
            return [dict(record) for record in result]

    def find_apis_for_goal(
        self,
        goal_keywords: List[str],
        platform_filter: Optional[str] = None,
    ) -> List[Dict]:
        """
        Find APIs relevant to a stated goal using keyword matching on names/descriptions.
        Then expand via relationships to find related APIs.
        """
        with self._driver.session() as session:
            platform_clause = "AND a.platform = $platform" if platform_filter else ""
            keyword_conditions = " OR ".join(
                [f"toLower(a.name) CONTAINS toLower($kw{i}) OR toLower(a.description) CONTAINS toLower($kw{i})"
                 for i in range(len(goal_keywords))]
            )
            params = {f"kw{i}": kw for i, kw in enumerate(goal_keywords)}
            if platform_filter:
                params["platform"] = platform_filter

            query = f"""
                MATCH (a:API)
                WHERE ({keyword_conditions}) {platform_clause}
                OPTIONAL MATCH (a)-[:PRECEDES|REQUIRES|TRIGGERS*1..3]->(related:API)
                WITH collect(DISTINCT a) + collect(DISTINCT related) AS all_apis
                UNWIND all_apis AS api
                RETURN DISTINCT
                    api.name AS name,
                    api.platform AS platform,
                    api.category AS category,
                    api.method AS method,
                    api.endpoint AS endpoint,
                    api.description AS description,
                    api.plain AS plain,
                    api.doc_url AS doc_url
                LIMIT 8
            """
            result = session.run(query, **params)
            return [dict(record) for record in result]

    def get_api_relationships(self, api_name: str) -> Dict:
        """Get all relationships for a specific API node."""
        with self._driver.session() as session:
            result = session.run("""
                MATCH (a:API) WHERE a.name CONTAINS $name
                OPTIONAL MATCH (a)-[:REQUIRES]->(req:API)
                OPTIONAL MATCH (a)-[:TRIGGERS]->(trig:API)
                OPTIONAL MATCH (a)-[:PRECEDES]->(prec:API)
                OPTIONAL MATCH (prev:API)-[:PRECEDES]->(a)
                RETURN
                    a.name AS name,
                    collect(DISTINCT req.name) AS requires,
                    collect(DISTINCT trig.name) AS triggers,
                    collect(DISTINCT prec.name) AS precedes,
                    collect(DISTINCT prev.name) AS preceded_by
            """, name=api_name)
            record = result.single()
            return dict(record) if record else {}

    def get_platform_apis(self, platform: str) -> List[Dict]:
        """Get all APIs for a given platform, ordered by category."""
        with self._driver.session() as session:
            result = session.run("""
                MATCH (a:API {platform: $platform})
                RETURN a.name AS name, a.category AS category,
                       a.method AS method, a.endpoint AS endpoint,
                       a.plain AS plain
                ORDER BY a.category, a.name
            """, platform=platform)
            return [dict(record) for record in result]

    def health_check(self) -> bool:
        """Verify Neo4j connection is healthy."""
        try:
            with self._driver.session() as session:
                session.run("RETURN 1")
            return True
        except Exception:
            return False
