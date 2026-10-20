"""Optional bounded Gemini runs through existing handlers; human review only."""

import argparse
import hashlib
import os
import tempfile
import time
from pathlib import Path

from evaluation.backends import BM25Backend, ProductionBackend, document_text, timed
from evaluation.dataset import fingerprints, load_dataset, read_jsonl, write_jsonl
from evaluation.metrics import latency_summary
from evaluation.run import environment, save_json


def validate_reviews(rows):
    seen = set()
    for row in rows:
        if row['query_id'] in seen:
            raise ValueError('Duplicate review ID')
        seen.add(row['query_id'])
        review = row.get('review', {})
        if not review:
            continue
        if not isinstance(row.get('answer'), str) or not row['answer'].strip():
            raise ValueError('Completed reviews require an actual answer')
        for field in ('factual_correctness', 'grounding'):
            if type(review.get(field)) is not int or review[field] not in (0, 1, 2):
                raise ValueError('Review scores must be integers from 0 to 2')
        if (type(review.get('unsupported_claims')) is not int or review['unsupported_claims'] < 0
                or type(review.get('abstained')) is not bool or not review.get('reviewer') or not review.get('notes')):
            raise ValueError('Review requires reviewer, notes, claim count and abstention flag')


def review_summary(rows):
    validate_reviews(rows)
    reviewed = [r for r in rows if r.get('review')]
    missing = [r for r in reviewed if not r['answerable']]
    return {
        'total': len(rows), 'reviewed': len(reviewed), 'pending': len(rows) - len(reviewed),
        'judge': 'human; subjective rubric, not objective ground truth',
        'factual_correctness': sum(r['review']['factual_correctness'] for r in reviewed) / (2 * len(reviewed)) if reviewed else None,
        'grounding': sum(r['review']['grounding'] for r in reviewed) / (2 * len(reviewed)) if reviewed else None,
        'unsupported_claim_rate': sum(r['review']['unsupported_claims'] > 0 for r in reviewed) / len(reviewed) if reviewed else None,
        'missing_information_abstention': sum(r['review']['abstained'] for r in missing) / len(missing) if missing else None,
        'abstention_n': len(missing),
    }


def review_rows(predictions, docs, questions, config='reranked'):
    by_id = {doc['id']: doc for doc in docs}
    by_query = {row['query_id']: row for row in predictions if row['config'] == config and row['repeat'] == 0}
    if set(by_query) != {q['id'] for q in questions}:
        raise ValueError('Review configuration must have a complete saved prediction set')
    return [{'query_id': q['id'], 'question': q['question'], 'category': q['category'],
             'answerable': q['answerable'], 'reference_answer': q['reference_answer'],
             'required_facts': q['required_facts'], 'expected_source_ids': q['expected_source_ids'],
             'retrieved_context': [by_id[doc] for doc in by_query.get(q['id'], {}).get('predicted_ids', [])],
             'answer': None, 'review': {}} for q in questions]


class CallBudget:
    """Pace actual requests per model; do not retry quota failures in this run."""

    def __init__(self, interval_seconds=13):
        if not 0 <= interval_seconds <= 60:
            raise ValueError('API interval must be between 0 and 60 seconds')
        self.interval = interval_seconds
        self.last_call = {}
        self.blocked = set()

    def before_call(self, model):
        if model in self.blocked:
            raise RuntimeError('Model quota unavailable; further requests suppressed')
        now = time.monotonic()
        wait = max(0, self.last_call.get(model, now - self.interval) + self.interval - now)
        if wait:
            time.sleep(wait)
        self.last_call[model] = now + wait
        return wait * 1000


class TimedModel:
    def __init__(self, model, label, calls, prices, budget=None):
        self.model, self.label, self.calls, self.prices = model, label, calls, prices
        self.budget = budget or CallBudget()

    def generate_content(self, prompt):
        from google.api_core.exceptions import GoogleAPICallError, ResourceExhausted, RetryError

        start = time.perf_counter_ns()
        record = {'model': self.label, 'prompt': prompt, 'error': None,
                  'api_request_sent': False, 'throttle_wait_ms': 0,
                  'input_tokens': None, 'output_tokens': None, 'total_tokens': None, 'estimated_usd': None}
        record['generation_config'] = dict(getattr(self.model, '_generation_config', {}))
        record['system_instruction_sha256'] = hashlib.sha256(
            str(getattr(self.model, '_system_instruction', '')).encode()).hexdigest()
        try:
            record['throttle_wait_ms'] = self.budget.before_call(self.label)
            start = time.perf_counter_ns()
            record['api_request_sent'] = True
            response = self.model.generate_content(prompt, request_options={'timeout': 60, 'retry': None})
            record['returned_model_version'] = getattr(response, 'model_version', None)
            candidates = getattr(response, 'candidates', [])
            record['finish_reasons'] = [int(c.finish_reason) for c in candidates]
            record['has_text'] = any(part.text for candidate in candidates for part in candidate.content.parts)
            usage = getattr(response, 'usage_metadata', None)
            if usage:
                record.update(input_tokens=usage.prompt_token_count,
                              output_tokens=usage.candidates_token_count,
                              total_tokens=usage.total_token_count)
                rate = self.prices.get(self.label)
                if rate:
                    record['estimated_usd'] = (record['input_tokens'] * rate['input_per_million'] +
                                               record['output_tokens'] * rate['output_per_million']) / 1_000_000
            return response
        except (GoogleAPICallError, RetryError, OSError, RuntimeError, ValueError) as exc:
            record['error'] = type(exc).__name__
            if isinstance(exc, ResourceExhausted):
                self.budget.blocked.add(self.label)
            raise
        finally:
            record['ms'] = (time.perf_counter_ns() - start) / 1_000_000
            self.calls.append(record)


class NoGraph:
    def find_apis_for_goal(self, **kwargs):
        return []


class BM25AnswerBackend:
    """Explicit lexical answer control; no dense retrieval or learned reranker."""

    def __init__(self, docs):
        self.lexical = BM25Backend(docs)
        self.docs = {doc['id']: doc for doc in docs}
        self.store = self
        self.reranker = self

    def count(self):
        return len(self.docs)

    def hybrid_search(self, query, top_k=6, platform_filter=None, category_filter=None):
        results = []
        for match in self.lexical.search(query, depth=self.count()):
            doc = self.docs[match['id']]
            entry = doc['entry']
            if platform_filter and entry['platform'] != platform_filter:
                continue
            if category_filter and entry['category'] != category_filter:
                continue
            results.append({'id': doc['id'], 'document': document_text(entry),
                            'metadata': entry, 'bm25_score': match['score']})
        return results[:top_k]

    def rerank(self, query, results, top_k=4):
        return results[:top_k]


def build_components(backend, key, calls, prices=None, api_interval_seconds=13):
    from query.advisory_handler import AdvisoryHandler
    from query.classifier import QueryClassifier
    from query.comparison_handler import ComparisonHandler
    from query.lookup_handler import LookupHandler
    from query.planning_handler import PlanningHandler

    classifier = QueryClassifier(key)
    budget = CallBudget(api_interval_seconds)
    handlers = dict(lookup=LookupHandler(backend.store, backend.reranker, key),
                    planning=PlanningHandler(backend.store, NoGraph(), backend.reranker, key),
                    advisory=AdvisoryHandler(backend.store, backend.reranker, key),
                    comparison=ComparisonHandler(backend.store, backend.reranker, key))
    for handler in [classifier, *handlers.values()]:
        for attr in ('_model', '_flash'):
            model = getattr(handler, attr, None)
            if model:
                label = 'gemini-2.5-pro' if isinstance(handler, (PlanningHandler, AdvisoryHandler)) and attr == '_model' else 'gemini-2.5-flash'
                setattr(handler, attr, TimedModel(model, label, calls, prices or {}, budget))
    return classifier, handlers


def generate(output, limit=12, prices=None, retrieval='production', api_interval_seconds=13):
    if not 1 <= limit <= 20:
        raise ValueError('Optional generation limited to 1..20 sequential questions')
    key = os.environ.get('GEMINI_API_KEY')
    if not key:
        raise ValueError('Set GEMINI_API_KEY in the process environment; .env is not loaded')
    if retrieval not in ('production', 'bm25'):
        raise ValueError('Choose production or bm25 retrieval')

    docs, questions = load_dataset()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'answers.jsonl').exists():
        raise ValueError('Use a fresh output directory')
    # Round-robin modes and then unanswerable items, rather than first N lookups.
    buckets = [[q for q in questions if q['mode'] == mode and q['answerable']]
               for mode in ('lookup', 'planning', 'advisory', 'comparison')]
    selected = [bucket[i] for i in range(2) for bucket in buckets]
    for category in ('ambiguous', 'absent', 'adversarial'):
        selected += [q for q in questions if not q['answerable'] and q['category'] == category][:1]
    selected += [q for q in questions if not q['answerable'] and q not in selected]
    selected = selected[:limit]
    calls, rows = [], []
    with tempfile.TemporaryDirectory(prefix='apirag-answer-evaluation-') as temporary:
        backend = BM25AnswerBackend(docs) if retrieval == 'bm25' else ProductionBackend(docs, temporary)
        if retrieval == 'production':
            backend.load_reranker()
        classifier, handlers = build_components(backend, key, calls, prices, api_interval_seconds)
        for q in selected:
            before = len(calls)
            start = time.perf_counter_ns()
            mode, method = classifier.classify(q['question'])
            response = handlers[mode].handle(q['question'])
            row = dict(query_id=q['id'], question=q['question'], category=q['category'],
                       answerable=q['answerable'], expected_mode=q['mode'], mode=mode,
                       classification_method=method, answer=response.answer, sources=response.sources,
                       reference_answer=q['reference_answer'], required_facts=q['required_facts'],
                       expected_source_ids=q['expected_source_ids'], review={},
                       retrieval_config=retrieval,
                       error='application_failure' if 'ran into an error' in response.answer.lower() else None,
                       handler_ms=(time.perf_counter_ns() - start) / 1_000_000,
                       calls=calls[before:], graph='disabled; dedicated graph experiment incomplete')
            rows.append(row)
            write_jsonl(output / 'answers.jsonl', rows)
            print(f"Generated {q['id']} via {mode} ({retrieval})", flush=True)
            time.sleep(1)  # Bound outbound model API pressure.
    save_json(output / 'answer_summary.json', {
        'review': review_summary(rows), 'environment': environment(), 'sha256': fingerprints(),
        'selection': [q['id'] for q in selected], 'prices': prices or {}, 'llm_judge': None,
        'retrieval_config': retrieval,
        'api_interval_seconds': api_interval_seconds,
        'model_latency': latency_summary([call['ms'] for call in calls if call['api_request_sent']]),
        'handler_latency': latency_summary([row['handler_ms'] for row in rows]),
        'handler_failures': sum(bool(row['error']) for row in rows),
        'model_call_failures': sum(bool(call['error']) for call in calls),
        'api_requests_sent': sum(call['api_request_sent'] for call in calls),
        'quota_suppressed_calls': sum(not call['api_request_sent'] for call in calls),
        'empty_model_responses': sum(call.get('has_text') is False for call in calls),
        'graph': 'incomplete; graph disabled for this answer run',
        'cost_caveat': 'User-supplied rates; input/output only, excludes unreported thinking/cache/billing adjustments.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--predictions', type=Path, required=True)
    prepare.add_argument('--config', default='reranked')
    prepare.add_argument('--output', type=Path, required=True)
    review = sub.add_parser('score')
    review.add_argument('--reviews', type=Path, required=True)
    review.add_argument('--output', type=Path, required=True)
    gen = sub.add_parser('generate')
    gen.add_argument('--output', type=Path, required=True)
    gen.add_argument('--limit', type=int, default=12)
    gen.add_argument('--retrieval', choices=['production', 'bm25'], default='production')
    gen.add_argument('--api-interval-seconds', type=float, default=13)
    gen.add_argument('--env-file', type=Path, help='Explicitly load credentials into this process only')
    gen.add_argument('--prices', type=Path, help='JSON model rates with input_per_million and output_per_million, date and source')
    args = parser.parse_args()
    if args.command == 'prepare':
        docs, questions = load_dataset()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.output, review_rows(read_jsonl(args.predictions), docs, questions, args.config))
    elif args.command == 'score':
        save_json(args.output, review_summary(read_jsonl(args.reviews)))
    else:
        import json

        if args.env_file:
            from dotenv import load_dotenv

            load_dotenv(args.env_file)
        generate(args.output, args.limit, json.loads(args.prices.read_text()) if args.prices else None, args.retrieval, args.api_interval_seconds)


if __name__ == '__main__':
    main()
