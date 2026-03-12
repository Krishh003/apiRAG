"""
Planning Handler — handles PLANNING queries (How do I achieve X?).

Uses:
  1. Extract goal keywords from question
  2. Graph traversal (Neo4j) to find related API workflow
  3. Vector + rerank to enrich with full parameter details
  4. Gemini Pro to generate structured step-by-step plan

Output format:
  Step N — API Name
    Endpoint: METHOD /path
    Purpose:  Why this step is needed
    Key parameters: name → description (required/optional)
    Returns:  What comes back
"""

import json
import logging
import re
from typing import List, Optional, Dict
import google.generativeai as genai
from retrieval.vector_store import VectorStore
from retrieval.graph_store import GraphStore
from retrieval.reranker import Reranker
from models import QueryResponse

logger = logging.getLogger(__name__)

PLANNING_SYSTEM = """You are a technical API integration expert helping a non-technical team understand exactly what API calls to make to achieve a goal.

Your output format must be EXACTLY as specified — structured steps with parameters.
Be precise about which parameters are required vs optional.
Use plain English for the purpose/explanation of each step.
Never invent parameters or endpoint paths not present in the context."""

KEYWORD_EXTRACT_PROMPT = """Extract 3-5 keywords from this query that describe the desired outcome.
Focus on nouns and verbs describing what needs to happen (not the word "API" or "call").
Return only a JSON array of strings.

Query: "{query}"

Example output: ["send", "whatsapp", "message", "customer"]"""

PLANNING_PROMPT = """A team member wants to achieve this goal: {question}

Here is the relevant API documentation for the APIs involved:

{context}

Generate a step-by-step API call plan. For each step use EXACTLY this format:

STEP [N] — [API Name]
  Platform:   [platform name]
  Endpoint:   [METHOD /path]
  Purpose:    [One sentence explaining why this step is needed, in plain English]
  Key parameters to pass:
    • [param_name] ([required/optional]) → [what to put here]
    • [param_name] ([required/optional]) → [what to put here]
  Returns:    [What the response gives you, and what to use in the next step]

After all steps, add:
IMPORTANT NOTES:
- [Any prerequisites, auth requirements, or common pitfalls]

Only include steps that are genuinely necessary. Do not pad with unnecessary steps.
Base everything strictly on the provided API documentation context."""


class PlanningHandler:

    def __init__(
        self,
        vector_store: VectorStore,
        graph_store: GraphStore,
        reranker: Reranker,
        gemini_api_key: str,
    ):
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._reranker = reranker
        genai.configure(api_key=gemini_api_key)

        # Gemini Pro for planning — better multi-hop reasoning
        self._model = genai.GenerativeModel(
            model_name="gemini-2.5-pro",
            system_instruction=PLANNING_SYSTEM,
            generation_config={"temperature": 0.1, "max_output_tokens": 1500},
        )
        # Flash for keyword extraction (cheap + fast)
        self._flash = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"temperature": 0, "max_output_tokens": 100},
        )

    def _extract_keywords(self, question: str) -> List[str]:
        """Extract goal keywords from the question using Gemini Flash."""
        try:
            response = self._flash.generate_content(
                KEYWORD_EXTRACT_PROMPT.format(query=question)
            )
            text = response.text.strip()
            # Strip markdown fences
            text = re.sub(r"```(?:json)?", "", text).strip().strip("`")
            keywords = json.loads(text)
            if isinstance(keywords, list):
                return [str(k) for k in keywords[:5]]
        except Exception as e:
            logger.warning(f"Keyword extraction failed: {e}")
        # Fallback: use important words from the question
        stopwords = {"how", "do", "i", "we", "the", "a", "an", "to", "what",
                     "api", "call", "calls", "need", "get", "make", "use"}
        return [w for w in question.lower().split() if w not in stopwords][:5]

    def _parse_plan_steps(self, plan_text: str) -> List[Dict]:
        """Parse the generated plan text into structured step dicts."""
        steps = []
        current_step = None

        for line in plan_text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Detect step header: STEP N — API Name
            step_match = re.match(r"^STEP\s+(\d+)\s*[—\-–]\s*(.+)$", line, re.IGNORECASE)
            if step_match:
                if current_step:
                    steps.append(current_step)
                current_step = {
                    "step": int(step_match.group(1)),
                    "api_name": step_match.group(2).strip(),
                    "platform": "",
                    "endpoint": "",
                    "purpose": "",
                    "parameters": [],
                    "returns": "",
                }
                continue

            if not current_step:
                continue

            # Parse fields
            if line.startswith("Platform:"):
                current_step["platform"] = line.replace("Platform:", "").strip()
            elif line.startswith("Endpoint:"):
                current_step["endpoint"] = line.replace("Endpoint:", "").strip()
            elif line.startswith("Purpose:"):
                current_step["purpose"] = line.replace("Purpose:", "").strip()
            elif line.startswith("Returns:"):
                current_step["returns"] = line.replace("Returns:", "").strip()
            elif line.startswith("•") or line.startswith("-"):
                # Parameter line
                param_text = line.lstrip("•-").strip()
                current_step["parameters"].append(param_text)

        if current_step:
            steps.append(current_step)

        return steps

    def handle(
        self,
        question: str,
        platform_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
    ) -> QueryResponse:

        # ── Step 1: Extract keywords ───────────────────────────────────────
        keywords = self._extract_keywords(question)
        logger.info(f"Planning keywords: {keywords}")

        # ── Step 2: Graph traversal ────────────────────────────────────────
        graph_apis = []
        try:
            graph_apis = self._graph_store.find_apis_for_goal(
                goal_keywords=keywords,
                platform_filter=platform_filter,
            )
            logger.info(f"Graph traversal found {len(graph_apis)} related APIs")
        except Exception as e:
            logger.warning(f"Graph traversal failed (continuing without): {e}")

        # ── Step 3: Vector search for same keywords ────────────────────────
        vector_results = self._vector_store.hybrid_search(
            query=question,
            top_k=10,
            platform_filter=platform_filter,
            category_filter=category_filter,
        )

        # ── Step 4: Rerank combined results ───────────────────────────────
        reranked = self._reranker.rerank(question, vector_results, top_k=6)

        if not reranked and not graph_apis:
            return QueryResponse(
                answer="I don't have enough API information to build a plan for this goal yet. Please populate the knowledge base using the scraper.",
                query_type="planning",
                sources=[],
                plan_steps=[],
            )

        # ── Step 5: Build context ──────────────────────────────────────────
        context_parts = []
        sources = []
        seen_names = set()

        # Add graph-discovered APIs first (they're most relevant to the workflow)
        for api in graph_apis:
            name = api.get("name", "")
            if name in seen_names:
                continue
            seen_names.add(name)
            context_parts.append(
                f"[API: {name}]\n"
                f"Platform: {api.get('platform', '')}\n"
                f"Method: {api.get('method', '')}\n"
                f"Endpoint: {api.get('endpoint', '')}\n"
                f"Description: {api.get('description', '')[:500]}\n"
                f"Plain: {api.get('plain', '')[:300]}"
            )
            sources.append({
                "name": name,
                "platform": api.get("platform", ""),
                "endpoint": api.get("endpoint", ""),
                "doc_url": api.get("doc_url", ""),
                "source": "graph",
            })

        # Add vector search results for parameter details
        for result in reranked:
            meta = result["metadata"]
            name = meta.get("name", "")
            if name in seen_names:
                continue
            seen_names.add(name)
            context_parts.append(f"[API: {name}]\n{result['document'][:700]}")
            sources.append({
                "name": name,
                "platform": meta.get("platform", ""),
                "endpoint": meta.get("endpoint", ""),
                "doc_url": meta.get("doc_url", ""),
                "source": "vector",
            })

        context = "\n\n---\n\n".join(context_parts[:8])

        # ── Step 6: Generate plan with Gemini Pro ──────────────────────────
        prompt = PLANNING_PROMPT.format(
            question=question,
            context=context,
        )

        try:
            response = self._model.generate_content(prompt)
            plan_text = response.text
        except Exception as e:
            logger.error(f"Gemini Pro planning generation failed: {e}")
            plan_text = "Sorry, I ran into an error generating the plan. Please try again."

        plan_steps = self._parse_plan_steps(plan_text)

        return QueryResponse(
            answer=plan_text,
            query_type="planning",
            sources=sources,
            plan_steps=plan_steps,
        )
