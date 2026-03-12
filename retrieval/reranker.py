"""
Cross-Encoder Reranker — re-scores retrieved chunks for accuracy.

After hybrid search returns top-K candidates, the reranker reads
the query and each full document together and re-scores them.
This is significantly more accurate than vector similarity alone
because it considers the query and document jointly.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
  - Fast: ~50ms for 6 documents
  - Good accuracy for technical documentation retrieval
"""

import logging
from typing import List, Dict, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_reranker():
    """Load reranker model once and cache it."""
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", max_length=512)
        logger.info("Cross-encoder reranker loaded")
        return model
    except Exception as e:
        logger.warning(f"Reranker load failed (will skip reranking): {e}")
        return None


class Reranker:

    def __init__(self):
        self._model = None  # Lazy load on first use

    def _get_model(self):
        if self._model is None:
            self._model = _load_reranker()
        return self._model

    def rerank(
        self,
        query: str,
        results: List[Dict],
        top_k: int = 4,
    ) -> List[Dict]:
        """
        Rerank a list of hybrid search results using cross-encoder.

        Each result dict must have a 'document' field.
        Returns top_k results sorted by rerank score descending.
        """
        if not results:
            return []

        model = self._get_model()
        if model is None:
            # Reranker unavailable — return as-is (still better than v1)
            logger.warning("Reranker unavailable, returning hybrid search order")
            return results[:top_k]

        # Build (query, document) pairs for the cross-encoder
        pairs = [(query, r["document"][:512]) for r in results]

        try:
            scores = model.predict(pairs)
        except Exception as e:
            logger.error(f"Reranker predict failed: {e}")
            return results[:top_k]

        # Attach rerank scores
        for result, score in zip(results, scores):
            result["rerank_score"] = float(score)

        # Sort by rerank score descending and return top_k
        reranked = sorted(results, key=lambda x: x.get("rerank_score", 0), reverse=True)
        return reranked[:top_k]
