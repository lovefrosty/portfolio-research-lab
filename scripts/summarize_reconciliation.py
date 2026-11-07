"""Recompute descriptive metrics; does not rerun historical model episodes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize() -> dict:
    base = ROOT / 'reports/reconciliation'
    rows = json.loads((base / 'episode-metrics.json').read_text())
    validation = json.loads((base / 'validation.json').read_text())
    usage = json.loads((base / 'total-model-usage.json').read_text())
    assert len(rows) == len({r['run'] for r in rows}) == 8
    assert {r['arm'] for r in rows} == {'graph', 'literal'}
    assert all(r['input_tokens'] - r['cached_input_tokens'] == r['uncached_input_tokens'] for r in rows)
    for prefix, expected in [('raw_model', 98), ('generated', 26), ('bound_narrative_claims', 32)]:
        if prefix == 'bound_narrative_claims':
            correct, total = prefix + '_correct', prefix + '_total'
        else:
            correct, total = prefix + '_values_correct', prefix + '_values_total'
        assert sum(r[correct] for r in rows) == sum(r[total] for r in rows) == expected
    assert sum(r['full_review_pass'] for r in rows) == validation['full_pass'] == 8
    for field in ['input_tokens', 'cached_input_tokens', 'output_tokens']:
        assert sum(r[field] for r in rows) == usage['benchmark_' + field]
        assert usage['benchmark_' + field] + usage['review_' + field] == usage['total_' + field]
    results = {}
    for arm in ['literal', 'graph']:
        group = [r for r in rows if r['arm'] == arm]
        assert len(group) == 4
        assert {(r['cohort'], r['case']) for r in group} == {(r['cohort'], r['case']) for r in rows}
        results['flat_bound' if arm == 'literal' else arm] = {
            'passes': sum(r['full_review_pass'] for r in group), 'cases': len(group),
            'uncached_input_tokens': sum(r['uncached_input_tokens'] for r in group),
            'episode_seconds': round(sum(r['seconds'] for r in group), 2),
        }
    return {'study': 'historical R31, 2026-10-14', 'arms': results,
            'model_calls_including_reviews': usage['total_model_calls'],
            'review_failures': usage['review_failures'],
            'interpretation': 'No observed accuracy advantage in four paired cases.',
            'verification_scope': 'Aggregation of published metadata; not a model or source-semantic replay.'}


if __name__ == '__main__':
    print(json.dumps(summarize(), indent=2))
