"""Load only the original synthetic benchmark, never production ingestion files."""

import hashlib
import json
from pathlib import Path

DATA = Path(__file__).parent / 'data'
CATEGORIES = {'endpoint', 'auth_parameters', 'planning', 'comparison', 'advisory',
              'ambiguous', 'absent', 'adversarial'}
MODES = {'lookup', 'planning', 'advisory', 'comparison'}


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path, rows):
    with Path(path).open('w', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + '\n')


def validate(docs, questions):
    doc_ids = [doc['id'] for doc in docs]
    question_ids = [q['id'] for q in questions]
    if not docs or not questions or len(doc_ids) != len(set(doc_ids)) or len(question_ids) != len(set(question_ids)):
        raise ValueError('Nonempty corpus/questions and unique IDs required')
    names = {doc['entry']['name'] for doc in docs}
    for doc in docs:
        if doc.get('provenance') != 'original-synthetic-v1' or doc['entry'].get('is_internal', False):
            raise ValueError('Only non-internal original synthetic documents allowed')
        if not doc['facts'] or not doc['entry']['base_url'].endswith('.example'):
            raise ValueError('Synthetic facts and reserved example domain required')
        for rel in ('requires', 'precedes', 'triggers'):
            if set(doc['entry'].get(rel, [])) - names:
                raise ValueError('Dangling relationship')
    for q in questions:
        if not isinstance(q['question'], str) or type(q['answerable']) is not bool:
            raise ValueError('Invalid question/answerability')
        if q['category'] not in CATEGORIES or q['mode'] not in MODES:
            raise ValueError('Invalid category/mode')
        if set(q['relevance']) - set(doc_ids) or any(type(v) is not int or v not in (1, 2) for v in q['relevance'].values()):
            raise ValueError('Invalid document relevance labels')
        if bool(q['relevance']) != q['answerable']:
            raise ValueError('Answerable items need sources; unanswerable items must have none')
        if not q['reference_answer'] or (q['answerable'] and not q['required_facts']):
            raise ValueError('Reference answer/facts required')
        if set(q['expected_source_ids']) != set(q['relevance']):
            raise ValueError('Source IDs and qrels disagree')


def load_dataset():
    docs = read_jsonl(DATA / 'corpus.jsonl')
    questions = read_jsonl(DATA / 'questions.jsonl')
    validate(docs, questions)
    return docs, questions


def fingerprints():
    return {name: hashlib.sha256((DATA / name).read_bytes()).hexdigest()
            for name in ('corpus.jsonl', 'questions.jsonl')}


if __name__ == '__main__':
    documents, items = load_dataset()
    print(json.dumps({'documents': len(documents), 'questions': len(items),
                      'answerable': sum(q['answerable'] for q in items), 'sha256': fingerprints()}, indent=2))
