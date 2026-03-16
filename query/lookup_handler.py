"""
Lookup Handler — handles LOOKUP queries (What does X do?).

Uses: Hybrid search → Reranker → Gemini Flash → Plain English answer
"""

import logging
from typing import Optional
import google.generativeai as genai
from retrieval.vector_store import VectorStore
from retrieval.reranker import Reranker
from models import QueryResponse

logger = logging.getLogger(__name__)

LOOKUP_SYSTEM = """You are a helpful assistant explaining technical APIs to non-technical people inside a company.

Your rules:
- Use plain, simple English. No jargon, no code, no technical acronyms without explanation.
- Focus on WHAT the API does and WHY the team would use it.
- Be concise — 2 to 4 sentences is ideal for simple questions.
- If the context doesn't fully answer the question, say so honestly.
- Never make up API behaviour — only use what's in the context."""

LOOKUP_PROMPT = """Context — relevant API documentation:

{context}

---

Question from a team member: {question}

Answer in plain English:"""


_CONF_THRESHOLD = 0.15  # sources below this are noise, not signal


def _compute_confidence(sources: list) -> tuple:
    all_scores = [s["relevance"] for s in sources if "relevance" in s]
    good = [s for s in all_scores if s >= _CONF_THRESHOLD]
    scores = good if good else all_scores  # fallback so we never return 0 unfairly
    if not scores:
        return 0.0, "low"
    raw = round(sum(scores) / len(scores), 2)
    label = "high" if raw >= 0.70 else "medium" if raw >= 0.40 else "low"
    return raw, label


class LookupHandler:

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
            system_instruction=LOOKUP_SYSTEM,
            generation_config={"temperature": 0.2, "max_output_tokens": 1500},
        )

    def handle(
        self,
        question: str,
        platform_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
    ) -> QueryResponse:

        # ── Retrieve ──────────────────────────────────────────────────────
        candidates = self._vector_store.hybrid_search(
            query=question,
            top_k=8,
            platform_filter=platform_filter,
            category_filter=category_filter,
        )

        if not candidates:
            return QueryResponse(
                answer="I don't have any API information stored yet. Please run the scraper to populate the knowledge base, or add APIs manually.",
                query_type="lookup",
                sources=[],
            )

        # ── Rerank ────────────────────────────────────────────────────────
        reranked = self._reranker.rerank(question, candidates, top_k=4)

        # ── Build context ─────────────────────────────────────────────────
        context_parts = []
        sources = []
        for i, result in enumerate(reranked, start=1):
            meta = result["metadata"]
            context_parts.append(f"[Source {i}: {meta.get('name', 'Unknown')}]\n{result['document'][:1500]}")
            sources.append({
                "name": meta.get("name", ""),
                "platform": meta.get("platform", ""),
                "category": meta.get("category", ""),
                "endpoint": meta.get("endpoint", ""),
                "method": meta.get("method", ""),
                "doc_url": meta.get("doc_url", ""),
                "relevance": round(result.get("rerank_score", result.get("vector_relevance", 0)), 3),
            })

        context = "\n\n---\n\n".join(context_parts)

        # ── Generate ──────────────────────────────────────────────────────
        prompt = LOOKUP_PROMPT.format(context=context, question=question)
        try:
            response = self._model.generate_content(prompt)
            answer = response.text
        except Exception as e:
            logger.error(f"Gemini lookup generation failed: {e}")
            answer = "Sorry, I ran into an error generating the answer. Please try again."

        confidence, confidence_label = _compute_confidence(sources)
        return QueryResponse(
            answer=answer,
            query_type="lookup",
            sources=sources,
            plan_steps=[],
            confidence=confidence,
            confidence_label=confidence_label,
        )
