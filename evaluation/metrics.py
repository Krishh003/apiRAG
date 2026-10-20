"""Ranking metrics and seeded query bootstrap; no ML dependencies."""

import math
import random
import statistics


def retrieval_metrics(predicted, relevance):
    if len(predicted) != len(set(predicted)):
        raise ValueError('Duplicate prediction IDs')
    relevant = {doc: grade for doc, grade in relevance.items() if grade > 0}
    if not relevant:
        return None
    gains = [relevant.get(doc, 0) for doc in predicted[:10]]
    dcg = sum((2 ** grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(gains))
    ideal = sorted(relevant.values(), reverse=True)[:10]
    idcg = sum((2 ** grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(ideal))
    return {
        'recall@1': len(set(predicted[:1]) & relevant.keys()) / len(relevant),
        'recall@5': len(set(predicted[:5]) & relevant.keys()) / len(relevant),
        'mrr@10': next((1 / (i + 1) for i, grade in enumerate(gains) if grade > 0), 0),
        'ndcg@10': dcg / idcg,
    }


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * quantile
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def aggregate(rows, seed=20261020, resamples=2000):
    rows = [row for row in rows if row is not None]
    if not rows:
        return None
    rng = random.Random(seed)
    keys = list(rows[0])
    samples = {key: [] for key in keys}
    for _ in range(resamples):
        draw = rng.choices(rows, k=len(rows))
        for key in keys:
            samples[key].append(statistics.mean(row[key] for row in draw))
    return {key: {
        'mean': statistics.mean(row[key] for row in rows),
        'ci95': [percentile(samples[key], .025), percentile(samples[key], .975)],
        'n': len(rows),
    } for key in keys}


def paired_delta(baseline, treatment, **kwargs):
    if len(baseline) != len(treatment):
        raise ValueError('Paired comparisons require matching queries')
    return aggregate([{key: b[key] - a[key] for key in a}
                      for a, b in zip(baseline, treatment) if a is not None and b is not None], **kwargs)


def latency_summary(milliseconds):
    return {'n': len(milliseconds), 'p50_ms': percentile(milliseconds, .5),
            'p95_ms': percentile(milliseconds, .95)}
