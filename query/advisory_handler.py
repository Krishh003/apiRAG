"""
Advisory Handler — handles ADVISORY queries.

These are questions that require data engineering expertise rather than
simple API documentation lookup. Examples:
  - "Why do Shopify purchase numbers differ from GA4?"
  - "What SQL query calculates daily revenue?"
  - "How should we design a data warehouse schema for ecommerce?"
  - "Why is ROAS decreasing despite stable traffic?"
  - "How should we structure incremental data pulls?"

Uses:
  1. Hybrid search to pull any relevant API entries from the KB as context
  2. Gemini 2.5 Pro with a data engineering expert system prompt
  3. Gemini may draw on general knowledge — KB context is supplementary grounding

The key difference from lookup_handler:
  - Lookup only answers from the KB context (never makes up API behaviour)
  - Advisory uses general data engineering expertise + KB context for grounding
"""

import logging
from typing import Optional
import google.generativeai as genai
from retrieval.vector_store import VectorStore
from retrieval.reranker import Reranker
from models import QueryResponse

logger = logging.getLogger(__name__)

ADVISORY_SYSTEM = """You are a knowledgeable data and analytics expert helping non-technical business users understand their data, tools, and reporting. You have deep knowledge of:
- Ecommerce analytics platforms (Shopify, GA4, Meta Ads, Google Ads, TikTok Ads)
- Mobile attribution tools (AppsFlyer, Firebase)
- Marketing attribution models and why numbers differ between platforms
- Data pipelines, dashboards, and reporting infrastructure
- SQL for business analytics

Your role: give clear, accurate, easy-to-understand answers to questions about data and analytics.

Rules:
- The audience is non-technical business users — marketers, managers, and analysts. Write for them.
- Use plain, everyday language. Avoid technical jargon; if a technical term is unavoidable, explain it in one sentence.
- Explain the "why" behind things, not just what to do.
- When explaining why numbers differ between platforms (e.g. Shopify vs GA4), use simple analogies to make the root cause easy to grasp.
- When asked for SQL, provide it and also explain in plain English what it does.
- Be specific and practical. Use bullet points or numbered steps so the answer is easy to follow.
- Use the API documentation context provided where relevant — it contains accurate details about the platforms in our knowledge base.
- If a question is outside your knowledge, say so clearly rather than guessing.
- Do NOT start your response with conversational openers like "Of course.", "Certainly.", "Sure.", "Great question.", or similar phrases. Start directly with the answer."""

ADVISORY_PROMPT = """Relevant API documentation from the knowledge base (use this as grounding context):

{context}

---

Data engineering question: {question}

Answer:"""

ADVISORY_PROMPT_NO_CONTEXT = """Data engineering question: {question}

Answer:"""


class AdvisoryHandler:

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
            model_name="gemini-2.5-pro",
            system_instruction=ADVISORY_SYSTEM,
            generation_config={"temperature": 0.3, "max_output_tokens": 2500},
        )

    def handle(
        self,
        question: str,
        platform_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
    ) -> QueryResponse:

        sources = []
        prompt = ADVISORY_PROMPT_NO_CONTEXT.format(question=question)

        # Pull relevant KB entries as grounding context if the KB has data
        try:
            candidates = self._vector_store.hybrid_search(
                query=question,
                top_k=8,
                platform_filter=platform_filter,
                category_filter=category_filter,
            )

            if candidates:
                reranked = self._reranker.rerank(question, candidates, top_k=4)

                context_parts = []
                for i, result in enumerate(reranked, start=1):
                    meta = result["metadata"]
                    context_parts.append(
                        f"[Source {i}: {meta.get('name', 'Unknown')} — {meta.get('platform', '')}]\n"
                        f"{result['document'][:1500]}"
                    )
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
                prompt = ADVISORY_PROMPT.format(context=context, question=question)

        except Exception as e:
            logger.warning(f"KB search failed for advisory query (proceeding without context): {e}")

        # Generate answer using Gemini Pro with data engineering expertise
        try:
            response = self._model.generate_content(prompt)
            answer = response.text
        except Exception as e:
            logger.error(f"Gemini Pro advisory generation failed: {e}")
            answer = "Sorry, I ran into an error generating the answer. Please try again."

        return QueryResponse(
            answer=answer,
            query_type="advisory",
            sources=sources,
            plan_steps=[],
        )
