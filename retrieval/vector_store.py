"""
Vector Store — ChromaDB with bge-large-en-v1.5 embeddings + BM25 hybrid search.

Key upgrades over v1:
  - bge-large-en-v1.5 (much more accurate than default all-MiniLM)
  - BM25 keyword search alongside vector search
  - Reciprocal Rank Fusion (RRF) to combine both scores
  - Structured metadata for precise platform/category filtering
"""

import logging
import uuid
from typing import List, Dict, Optional, Tuple
from rank_bm25 import BM25Okapi
import chromadb
from chromadb.utils import embedding_functions
from models import APIEntry

logger = logging.getLogger(__name__)


def _entry_to_document(entry: APIEntry) -> str:
    """Convert APIEntry to a single searchable text document."""
    param_text = ""
    if entry.parameters:
        param_lines = [
            f"  - {p.name} ({'required' if p.required else 'optional'}): {p.description}"
            for p in entry.parameters[:10]
        ]
        param_text = "Parameters:\n" + "\n".join(param_lines)

    return (
        f"API Name: {entry.name}\n"
        f"Platform: {entry.platform}\n"
        f"Category: {entry.category}\n"
        f"Method: {entry.method}\n"
        f"Endpoint: {entry.endpoint}\n"
        f"Auth: {entry.auth}\n"
        f"{param_text}\n"
        f"Description: {entry.description}\n"
        f"Plain Explanation: {entry.plain_explanation}\n"
        f"Requires: {', '.join(entry.requires)}\n"
        f"Triggers: {', '.join(entry.triggers)}\n"
        f"Precedes: {', '.join(entry.precedes)}"
    ).strip()


def _entry_to_metadata(entry: APIEntry) -> Dict:
    """Build ChromaDB metadata dict from an APIEntry."""
    return {
        "name": entry.name,
        "platform": entry.platform,
        "category": entry.category,
        "method": entry.method,
        "endpoint": entry.endpoint,
        "auth": entry.auth[:200] if entry.auth else "",
        "doc_url": entry.doc_url,
        "is_internal": str(entry.is_internal),
        "requires": "|".join(entry.requires),
        "triggers": "|".join(entry.triggers),
        "precedes": "|".join(entry.precedes),
    }


class VectorStore:

    def __init__(self, chroma_path: str = "./chroma_db"):
        # Use bge-large for high accuracy — significantly better than default
        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="BAAI/bge-large-en-v1.5",
            device="cpu",
        )
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._collection = self._client.get_or_create_collection(
            name="api_docs_v2",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

        # BM25 index (in-memory, rebuilt on each upsert)
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_ids: List[str] = []
        self._bm25_docs: List[str] = []
        self._rebuild_bm25()

    # ── Write operations ──────────────────────────────────────────────────

    def upsert_entries(self, entries: List[APIEntry]) -> int:
        """
        Upsert a list of APIEntry objects.
        Uses entry name + platform as natural key for deduplication.
        """
        if not entries:
            return 0

        # Fetch existing entries to detect duplicates by name+platform
        existing = self._collection.get(include=["metadatas"])
        existing_keys = {
            f"{m['platform']}::{m['name']}"
            for m in existing["metadatas"]
        }
        existing_id_by_key = {
            f"{m['platform']}::{m['name']}": existing["ids"][i]
            for i, m in enumerate(existing["metadatas"])
        }

        to_add_ids, to_add_docs, to_add_metas = [], [], []
        to_update_ids, to_update_docs, to_update_metas = [], [], []

        for entry in entries:
            key = f"{entry.platform}::{entry.name}"
            doc = _entry_to_document(entry)
            meta = _entry_to_metadata(entry)

            if key in existing_keys:
                to_update_ids.append(existing_id_by_key[key])
                to_update_docs.append(doc)
                to_update_metas.append(meta)
            else:
                to_add_ids.append(str(uuid.uuid4()))
                to_add_docs.append(doc)
                to_add_metas.append(meta)

        if to_add_docs:
            self._collection.add(
                documents=to_add_docs,
                metadatas=to_add_metas,
                ids=to_add_ids,
            )

        if to_update_docs:
            self._collection.update(
                documents=to_update_docs,
                metadatas=to_update_metas,
                ids=to_update_ids,
            )

        self._rebuild_bm25()
        total = len(to_add_docs) + len(to_update_docs)
        logger.info(f"VectorStore upsert: {len(to_add_docs)} added, {len(to_update_docs)} updated")
        return total

    def delete_entry(self, entry_id: str):
        self._collection.delete(ids=[entry_id])
        self._rebuild_bm25()

    # ── BM25 ──────────────────────────────────────────────────────────────

    def _rebuild_bm25(self):
        """Rebuild the BM25 index from all documents in ChromaDB."""
        try:
            results = self._collection.get(include=["documents"])
            if not results["documents"]:
                self._bm25 = None
                self._bm25_ids = []
                self._bm25_docs = []
                return

            self._bm25_ids = results["ids"]
            self._bm25_docs = results["documents"]
            tokenized = [doc.lower().split() for doc in self._bm25_docs]
            self._bm25 = BM25Okapi(tokenized)
        except Exception as e:
            logger.error(f"BM25 rebuild failed: {e}")
            self._bm25 = None

    def _bm25_search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """BM25 keyword search. Returns list of (id, score) tuples."""
        if not self._bm25 or not self._bm25_ids:
            return []
        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self._bm25_ids[i], float(score)) for i, score in indexed if score > 0]

    # ── Search ────────────────────────────────────────────────────────────

    def hybrid_search(
        self,
        query: str,
        top_k: int = 6,
        platform_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
    ) -> List[Dict]:
        """
        Hybrid search: combines vector similarity + BM25 keyword search
        using Reciprocal Rank Fusion (RRF).

        Returns list of dicts with entry metadata + combined score.
        """
        n = self._collection.count()
        if n == 0:
            return []

        where = {}
        if platform_filter:
            where["platform"] = platform_filter
        if category_filter:
            where["category"] = category_filter

        # ── Vector search ─────────────────────────────────────────────────
        vector_results = self._collection.query(
            query_texts=[query],
            n_results=min(top_k * 2, n),
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        # Map id → vector rank (1-indexed)
        vector_ranks: Dict[str, int] = {}
        vector_distances: Dict[str, float] = {}
        if vector_results["ids"] and vector_results["ids"][0]:
            for rank, (vid, dist) in enumerate(
                zip(vector_results["ids"][0], vector_results["distances"][0]), start=1
            ):
                vector_ranks[vid] = rank
                vector_distances[vid] = float(dist)

        # ── BM25 search ───────────────────────────────────────────────────
        bm25_results = self._bm25_search(query, top_k=top_k * 2)
        bm25_ranks: Dict[str, int] = {}
        for rank, (bid, _) in enumerate(bm25_results, start=1):
            bm25_ranks[bid] = rank

        # ── Reciprocal Rank Fusion (RRF) ──────────────────────────────────
        k = 60  # RRF constant
        all_ids = set(vector_ranks.keys()) | set(bm25_ranks.keys())
        rrf_scores: Dict[str, float] = {}
        for doc_id in all_ids:
            v_rank = vector_ranks.get(doc_id, len(all_ids) + 1)
            b_rank = bm25_ranks.get(doc_id, len(all_ids) + 1)
            rrf_scores[doc_id] = 1 / (k + v_rank) + 1 / (k + b_rank)

        # Sort by RRF score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k]

        # Fetch full metadata for top results
        if not sorted_ids:
            return []

        fetched = self._collection.get(
            ids=sorted_ids,
            include=["documents", "metadatas"],
        )

        results = []
        for i, (doc_id, doc, meta) in enumerate(zip(
            fetched["ids"], fetched["documents"], fetched["metadatas"]
        )):
            results.append({
                "id": doc_id,
                "document": doc,
                "metadata": meta,
                "rrf_score": round(rrf_scores.get(doc_id, 0), 4),
                "vector_distance": round(vector_distances.get(doc_id, 1.0), 4),
                "vector_relevance": round(1 - vector_distances.get(doc_id, 1.0), 4),
            })

        # Sort by RRF score
        results.sort(key=lambda x: x["rrf_score"], reverse=True)
        return results

    # ── Read helpers ──────────────────────────────────────────────────────

    def list_all(self) -> List[Dict]:
        results = self._collection.get(include=["metadatas"])
        items = []
        for i, meta in enumerate(results["metadatas"]):
            items.append({"id": results["ids"][i], **meta})
        items.sort(key=lambda x: (x.get("platform", ""), x.get("name", "")))
        return items

    def get_platforms(self) -> List[str]:
        results = self._collection.get(include=["metadatas"])
        return sorted({m.get("platform", "") for m in results["metadatas"] if m.get("platform")})

    def get_categories(self, platform: Optional[str] = None) -> List[str]:
        results = self._collection.get(include=["metadatas"])
        cats = {
            m.get("category", "")
            for m in results["metadatas"]
            if m.get("category") and (not platform or m.get("platform") == platform)
        }
        return sorted(cats)

    def count(self) -> int:
        return self._collection.count()
