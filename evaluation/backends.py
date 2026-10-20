"""Evaluation adapters. Production objects are only used with a fresh index."""

import hashlib
import os
import time


def document_text(entry):
    # Same serialized fields as _entry_to_document; parity checked by integration test.
    parameters = entry.get('parameters', [])[:10]
    param_text = 'Parameters:\n' + '\n'.join(
        f"  - {p['name']} ({'required' if p.get('required') else 'optional'}): {p.get('description', '')}"
        for p in parameters) if parameters else ''
    return (f"API Name: {entry['name']}\nPlatform: {entry['platform']}\n"
            f"Category: {entry['category']}\nMethod: {entry.get('method', 'GET')}\n"
            f"Endpoint: {entry['endpoint']}\nAuth: {entry.get('auth', '')}\n{param_text}\n"
            f"Description: {entry['description']}\nPlain Explanation: {entry['plain_explanation']}\n"
            f"Requires: {', '.join(entry.get('requires', []))}\n"
            f"Triggers: {', '.join(entry.get('triggers', []))}\n"
            f"Precedes: {', '.join(entry.get('precedes', []))}").strip()


def production_rrf(dense_ids, bm25_ids, k=60):
    union = set(dense_ids) | set(bm25_ids)
    dense = {doc: rank for rank, doc in enumerate(dense_ids, 1)}
    bm25 = {doc: rank for rank, doc in enumerate(bm25_ids, 1)}
    return {doc: 1 / (k + dense.get(doc, len(union) + 1)) +
            1 / (k + bm25.get(doc, len(union) + 1)) for doc in union}


class BM25Backend:
    def __init__(self, docs):
        from rank_bm25 import BM25Okapi

        self.ids = [doc['id'] for doc in docs]
        self.documents = [document_text(doc['entry']) for doc in docs]
        self.index = BM25Okapi([doc.lower().split() for doc in self.documents]) if docs else None

    def search(self, question, depth=20):
        if not question.strip() or self.index is None:
            return []
        scores = self.index.get_scores(question.lower().split())
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:depth]
        return [{'id': self.ids[i], 'score': float(score)} for i, score in ranked if score > 0]


class ProductionBackend:
    def __init__(self, docs, path):
        from chromadb.utils import embedding_functions
        from sentence_transformers import SentenceTransformer

        from models import APIEntry
        from retrieval.vector_store import VectorStore, _entry_to_document, _entry_to_metadata

        revision = os.getenv('EVAL_EMBEDDING_REVISION')
        if revision:
            embedding_functions.SentenceTransformerEmbeddingFunction.models['BAAI/bge-large-en-v1.5'] = SentenceTransformer(
                'BAAI/bge-large-en-v1.5', revision=revision, device='cpu')
        self.store = VectorStore(chroma_path=str(path))
        try:
            entries = [APIEntry(**doc['entry']) for doc in docs]
            self.store._collection.add(ids=[doc['id'] for doc in docs],
                                       documents=[_entry_to_document(entry) for entry in entries],
                                       metadatas=[_entry_to_metadata(entry) for entry in entries])
            self.store._rebuild_bm25()
        except (ValueError, RuntimeError, OSError):
            self.close()
            raise
        self.reranker = None

    def close(self):
        # Chroma 0.5 keeps HNSW files open on Windows until its owned system stops.
        self.store._client._system.stop()

    def load_reranker(self):
        from retrieval.reranker import Reranker

        self.reranker = Reranker()
        revision = os.getenv('EVAL_RERANKER_REVISION')
        if revision:
            from sentence_transformers import CrossEncoder

            self.reranker._model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', revision=revision, max_length=512)
        if self.reranker._get_model() is None:
            raise RuntimeError('Cross encoder unavailable; hybrid fallback is not a rerank experiment')

    def model_manifest(self):
        def describe(model, tokenizer):
            # Hash loaded weights once, outside timing; names alone are mutable.
            digest = hashlib.sha256()
            for key, value in sorted(model.state_dict().items()):
                tensor = value.detach().cpu().contiguous()
                digest.update(key.encode())
                digest.update(str((tensor.dtype, tuple(tensor.shape))).encode())
                digest.update(tensor.numpy().tobytes())
            vocabulary = sorted(tokenizer.get_vocab().items())
            return {'revision': getattr(model.config, '_commit_hash', None),
                    'weights_sha256': digest.hexdigest(),
                    'tokenizer_vocab_sha256': hashlib.sha256(repr(vocabulary).encode()).hexdigest(),
                    'tokenizer_config_sha256': hashlib.sha256(repr(sorted(tokenizer.init_kwargs.items())).encode()).hexdigest(),
                    'device': str(next(model.parameters()).device)}

        sentence_model = self.store._ef._model._first_module()
        result = {'embedding': describe(sentence_model.auto_model, sentence_model.tokenizer)}
        if self.reranker is not None and self.reranker._model is not None:
            cross = self.reranker._model
            result['reranker'] = describe(cross.model, cross.tokenizer)
        return result

    def dense(self, question, depth=20):
        if not question.strip():
            return []
        result = self.store._collection.query(query_texts=[question],
                                               n_results=min(depth, self.store.count()),
                                               include=['distances'])
        return [{'id': doc_id, 'score': 1 - float(distance)}
                for doc_id, distance in zip(result['ids'][0], result['distances'][0])]

    def hybrid(self, question, depth=10):
        return self.store.hybrid_search(question, top_k=depth) if question.strip() else []

    def rerank(self, question, candidates, depth=10):
        if not candidates:
            return []
        result = self.reranker.rerank(question, [dict(row) for row in candidates], top_k=depth)
        if any('rerank_score' not in row for row in result):
            raise RuntimeError('Cross encoder failed; silent production fallback detected')
        return result


def timed(function, *args, **kwargs):
    start = time.perf_counter_ns()
    result = function(*args, **kwargs)
    return result, (time.perf_counter_ns() - start) / 1_000_000
