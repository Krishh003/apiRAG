"""
Comparison Handler — handles COMPARISON queries (What is the difference between X, Y, and Z?).

Every source is retrieved and scored against its own concept query, ensuring
per-source relevance scores are meaningful (no mixing with full-question scoring).

Pipeline:
  Full-question search → infer platforms
  Gemini extracts concepts
  Per-concept: targeted search → rerank vs concept → top-1 source
  Gemini Flash with comparison-specific prompt
"""

import logging
from collections import Counter
from typing import Optional
import google.generativeai as genai
from retrieval.vector_store import VectorStore
from retrieval.reranker import Reranker
from models import QueryResponse

logger = logging.getLogger(__name__)

COMPARISON_SYSTEM = """You are a helpful assistant comparing API operations for non-technical team members.

Your rules:
- Compare each item clearly, one at a time — use bullet points or numbered items, one per concept
- Use plain, simple English. No jargon, no code snippets.
- Focus on WHAT each operation does and HOW it differs from the others.
- Only use information from the provided context.
- If a concept is missing from the context, say so explicitly rather than guessing."""

COMPARISON_PROMPT = """Context — one section per API operation being compared:

{context}

---

Question from a team member: {question}

Provide a clear comparison in plain English, one item per operation:"""

_CONCEPT_PROMPT = (
    "Extract the full names of the API operations being compared in this question. "
    "Each name must include its full context — for example if comparing 'creating' and 'capturing' a PaymentIntent, "
    "return 'Create a PaymentIntent, Capture a PaymentIntent', not just 'creating, capturing'. "
    "Return ONLY a comma-separated list of complete operation names, nothing else.\n"
    "Question: {question}\nOperations:"
)


class ComparisonHandler:

    def __init__(
        self,
        vector_store: VectorStore,
        reranker: Reranker,
        gemini_api_key: str,
    ):
        self._vector_store = vector_store
        self._reranker = reranker
        genai.configure(api_key=gemini_api_key)
        self._model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=COMPARISON_SYSTEM,
            generation_config={"temperature": 0.2, "max_output_tokens": 1500},
        )

    def handle(
        self,
        question: str,
        platform_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
    ) -> QueryResponse:

        # ── Step 1: Full-question search to infer platform context ────────────
        orig_results = self._vector_store.hybrid_search(
            query=question,
            top_k=6,
            platform_filter=platform_filter,
            category_filter=category_filter,
        )

        if not platform_filter and orig_results:
            votes = Counter(r["metadata"].get("platform", "") for r in orig_results)
            allowed_platforms = {p for p, _ in votes.most_common(2) if p}
        elif platform_filter:
            allowed_platforms = {platform_filter}
        else:
            allowed_platforms = set()

        # Single-platform filter string for ChromaDB (takes one value only)
        pf = list(allowed_platforms)[0] if len(allowed_platforms) == 1 else platform_filter

        # ── Step 2: Extract individual concepts ──────────────────────────────
        try:
            cr = self._model.generate_content(_CONCEPT_PROMPT.format(question=question))
            concepts = [c.strip() for c in cr.text.split(",") if c.strip()][:4]
        except Exception:
            concepts = []

        if not concepts and not orig_results:
            return QueryResponse(
                answer="I don't have any API information stored yet. Please run the scraper to populate the knowledge base, or add APIs manually.",
                query_type="comparison",
                sources=[],
            )

        # ── Step 3: Per-concept retrieval and scoring ─────────────────────────
        # Each concept gets its own search + rerank scored against the concept
        # (not the full question), so every source shows a meaningful relevance.
        sources = []
        context_parts = []
        seen_ids: set = set()

        for concept in concepts:
            candidates = [
                r for r in self._vector_store.hybrid_search(
                    query=concept,
                    top_k=4,
                    platform_filter=pf,
                    category_filter=category_filter,
                )
                if not allowed_platforms or r["metadata"].get("platform", "") in allowed_platforms
            ]

            if not candidates:
                # Fallback: try without platform filter in case the concept is cross-platform
                candidates = self._vector_store.hybrid_search(
                    query=concept, top_k=3, category_filter=category_filter
                )

            if not candidates:
                continue

            # Rerank against the CONCEPT (not the full question) so the top doc
            # for this concept scores high regardless of whether it contains
            # comparison language.
            ranked = self._reranker.rerank(concept, candidates, top_k=1)
            best = ranked[0] if ranked else candidates[0]

            if best["id"] in seen_ids:
                continue
            seen_ids.add(best["id"])

            meta = best["metadata"]
            relevance = round(best.get("rerank_score", best.get("vector_relevance", 0)), 3)
            context_parts.append(
                f"[{concept}]\n{best['document'][:1500]}"
            )
            sources.append({
                "name": meta.get("name", ""),
                "platform": meta.get("platform", ""),
                "category": meta.get("category", ""),
                "endpoint": meta.get("endpoint", ""),
                "method": meta.get("method", ""),
                "doc_url": meta.get("doc_url", ""),
                "relevance": relevance,
                "concept": concept,
            })

        # If concept extraction failed entirely, fall back to top orig_results
        if not context_parts and orig_results:
            for result in orig_results[:4]:
                meta = result["metadata"]
                context_parts.append(f"[{meta.get('name', 'Unknown')}]\n{result['document'][:1500]}")
                sources.append({
                    "name": meta.get("name", ""),
                    "platform": meta.get("platform", ""),
                    "category": meta.get("category", ""),
                    "endpoint": meta.get("endpoint", ""),
                    "method": meta.get("method", ""),
                    "doc_url": meta.get("doc_url", ""),
                    "relevance": round(result.get("vector_relevance", 0), 3),
                })

        context = "\n\n---\n\n".join(context_parts)

        # ── Step 4: Generate ──────────────────────────────────────────────────
        prompt = COMPARISON_PROMPT.format(context=context, question=question)
        try:
            response = self._model.generate_content(prompt)
            answer = response.text
        except Exception as e:
            logger.error(f"Gemini comparison generation failed: {e}")
            answer = "Sorry, I ran into an error generating the answer. Please try again."

        # Confidence = mean of per-concept scores (all came from targeted searches)
        scores = [s["relevance"] for s in sources if s.get("relevance", 0) > 0]
        confidence = round(sum(scores) / len(scores), 2) if scores else 0.0
        confidence_label = "high" if confidence >= 0.70 else "medium" if confidence >= 0.40 else "low"

        return QueryResponse(
            answer=answer,
            query_type="comparison",
            sources=sources,
            plan_steps=[],
            confidence=confidence,
            confidence_label=confidence_label,
        )
