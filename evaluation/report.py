"""Render report tables and plots exclusively from saved experiment evidence."""

import argparse
import json
from pathlib import Path

from evaluation.dataset import load_dataset, read_jsonl
from evaluation.run import score_predictions


def report(run, destination):
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    run, destination = Path(run), Path(destination)
    summary = json.loads((run / 'summary.json').read_text())
    _, questions = load_dataset()
    scored = score_predictions(read_jsonl(run / 'predictions.jsonl'), questions)
    if scored['retrieval'] != summary['retrieval']:
        raise ValueError('Summary does not match saved predictions/labels')
    destination.mkdir(parents=True, exist_ok=True)
    lines = ['# Offline evaluation results', '',
             'Generated from saved predictions and frozen synthetic qrels. These are retrieval results, not answer correctness.', '',
             f"Documents: {summary['counts']['documents']}; queries: {summary['counts']['questions']}; retrieval-labeled: {summary['counts']['answerable']}.", '',
             '| Configuration | Recall@1 | Recall@5 | MRR@10 | nDCG@10 |',
             '|---|---:|---:|---:|---:|']
    names = list(scored['retrieval'])
    for name in names:
        metrics = scored['retrieval'][name]['overall']
        cells = [f"{metrics[key]['mean']:.4f} [{metrics[key]['ci95'][0]:.4f}, {metrics[key]['ci95'][1]:.4f}]"
                 for key in ('recall@1', 'recall@5', 'mrr@10', 'ndcg@10')]
        lines.append('| ' + name + ' | ' + ' | '.join(cells) + ' |')
    lines += ['', 'Brackets: 95% query-bootstrap percentile intervals (2000 resamples, seed 20261020).',
              'Repeated runs are reported separately; repeated queries are not pooled as independent evidence.', '',
              '## Paired differences', '', '| Treatment minus baseline | Metric | Mean delta | 95% CI |', '|---|---|---:|---|']
    for name, metrics in scored['paired_deltas'].items():
        for key, value in metrics.items():
            lines.append(f"| {name} | {key} | {value['mean']:+.4f} | [{value['ci95'][0]:+.4f}, {value['ci95'][1]:+.4f}] |")
    lines += ['', 'Intervals include query sampling uncertainty only; synthetic authoring bias and corpus mismatch are not captured.',
              '', '## Warm local performance', '', '| Stage | Samples | p50 ms | p95 ms |', '|---|---:|---:|---:|']
    for name, value in summary['latencies'].items():
        lines.append(f"| {name} | {value['n']} | {value['p50_ms']:.3f} | {value['p95_ms']:.3f} |")
    concurrency = summary['concurrency']
    lines += ['', f"Local {concurrency['configuration']} concurrency: {concurrency['n']} requests, {concurrency['workers']} workers; "
              f"failures {concurrency['failures']}/{concurrency['n']} ({concurrency['failure_rate']:.1%}); "
              f"p50 {concurrency['p50_ms']:.3f} ms, p95 {concurrency['p95_ms']:.3f} ms.",
              'This is a small thread-pool retrieval test; it excludes HTTP, Gemini and event-loop contention.', '',
              '## Experiment status', '', '| Stage | Status | Attempts | Failures | Reason |', '|---|---|---:|---:|---|']
    for name, value in summary['stages'].items():
        lines.append(f"| {name} | {value['status']} | {value.get('attempted', 0)} | {value.get('failed', 0)} | {value.get('reason', '')} |")
    lines += ['', 'See [methods and limitations](README.md), [repository audit](audit.md), and [human review](human-review.md).',
              '', '![Retrieval metrics](retrieval.png)', '', '![Warm stage latency](latency.png)', '']
    (destination / 'results.md').write_text('\n'.join(lines), encoding='utf-8')

    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for ax, metric in zip(axes, ('mrr@10', 'recall@5')):
        values = [scored['retrieval'][name]['overall'][metric] for name in names]
        ax.bar(names, [v['mean'] for v in values], color='#34656d')
        ax.errorbar(names, [v['mean'] for v in values],
                    yerr=[[v['mean'] - v['ci95'][0] for v in values],
                          [v['ci95'][1] - v['mean'] for v in values]], fmt='none', color='black', capsize=4)
        ax.set_ylim(0, 1.06)
        ax.set_title(metric + ' (95% query bootstrap CI)')
        ax.tick_params(axis='x', labelrotation=20)
    fig.savefig(destination / 'retrieval.png', dpi=160)
    plt.close(fig)
    stages = summary['latencies']
    fig, ax = plt.subplots(figsize=(9, 4), constrained_layout=True)
    stages = {k: v for k, v in stages.items() if v['p50_ms'] > 0}
    ax.bar(list(stages), [v['p50_ms'] for v in stages.values()], color='#34656d', label='p50')
    ax.scatter(list(stages), [v['p95_ms'] for v in stages.values()], color='#ad5c37', label='p95')
    ax.set_yscale('log')
    ax.set_ylabel('Milliseconds (log scale)')
    ax.set_title('Warm local stages; fusion kernel excludes searches')
    ax.tick_params(axis='x', labelrotation=20)
    ax.legend()
    fig.savefig(destination / 'latency.png', dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report(args.run, args.output)
