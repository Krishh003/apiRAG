"""Optional bounded Gemini runs through existing handlers; human review only."""

import argparse
import os
import tempfile
import time
from pathlib import Path

from evaluation.backends import ProductionBackend, timed
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


class TimedModel:
    def __init__(self, model, label, calls, prices):
        self.model, self.label, self.calls, self.prices = model, label, calls, prices

    def generate_content(self, prompt):
        from google.api_core.exceptions import GoogleAPICallError, RetryError

        start = time.perf_counter_ns()
        record = {'model': self.label, 'prompt': prompt, 'error': None,
                  'input_tokens': None, 'output_tokens': None, 'total_tokens': None, 'estimated_usd': None}
        try:
            response = self.model.generate_content(prompt, request_options={'timeout': 60})
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
            raise
        finally:
            record['ms'] = (time.perf_counter_ns() - start) / 1_000_000
            self.calls.append(record)


class NoGraph:
    def find_apis_for_goal(self, **kwargs):
        return []


def generate(output, limit=12, prices=None):
    if not 1 <= limit <= 20:
        raise ValueError('Optional generation limited to 1..20 sequential questions')
    key = os.environ.get('GEMINI_API_KEY')
    if not key:
        raise ValueError('Set GEMINI_API_KEY in the process environment; .env is not loaded')
    from query.advisory_handler import AdvisoryHandler
    from query.classifier import QueryClassifier
    from query.comparison_handler import ComparisonHandler
    from query.lookup_handler import LookupHandler
    from query.planning_handler import PlanningHandler

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
        backend = ProductionBackend(docs, temporary)
        backend.load_reranker()
        classifier = QueryClassifier(key)
        handlers = dict(lookup=LookupHandler(backend.store, backend.reranker, key),
                        planning=PlanningHandler(backend.store, NoGraph(), backend.reranker, key),
                        advisory=AdvisoryHandler(backend.store, backend.reranker, key),
                        comparison=ComparisonHandler(backend.store, backend.reranker, key))
        for handler in [classifier, *handlers.values()]:
            for attr in ('_model', '_flash'):
                model = getattr(handler, attr, None)
                if model:
                    label = 'gemini-2.5-pro' if isinstance(handler, (PlanningHandler, AdvisoryHandler)) and attr == '_model' else 'gemini-2.5-flash'
                    setattr(handler, attr, TimedModel(model, label, calls, prices or {}))
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
                       error='application_failure' if 'ran into an error' in response.answer.lower() else None,
                       handler_ms=(time.perf_counter_ns() - start) / 1_000_000,
                       calls=calls[before:], graph='disabled; dedicated graph experiment incomplete')
            rows.append(row)
            write_jsonl(output / 'answers.jsonl', rows)
            time.sleep(1)  # Bound outbound model API pressure.
    save_json(output / 'answer_summary.json', {
        'review': review_summary(rows), 'environment': environment(), 'sha256': fingerprints(),
        'selection': [q['id'] for q in selected], 'prices': prices or {}, 'llm_judge': None,
        'model_latency': latency_summary([call['ms'] for call in calls]),
        'handler_latency': latency_summary([row['handler_ms'] for row in rows]),
        'handler_failures': sum(bool(row['error']) for row in rows),
        'model_call_failures': sum(bool(call['error']) for call in calls),
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

        generate(args.output, args.limit, json.loads(args.prices.read_text()) if args.prices else None)


if __name__ == '__main__':
    main()
