"""Numerical replay of a fixed one-feature ridge specification.

New standard-library implementation of the historical formula, not a new model
selection exercise. It consumes already-admitted cases; source admission and
historical completeness are outside its scope.
"""
from __future__ import annotations

from datetime import date, timedelta
import math
import statistics

LANES = ('pooled_expanding', 'leave_one_issuer_out_expanding')


def validate_cases(cases: list[dict]) -> dict[str, dict]:
    lookup = {}
    for c in cases:
        if c['id'] in lookup:
            raise ValueError('duplicate_case')
        lookup[c['id']] = c
        origin = date.fromisoformat(c['origin'])
        regimes = set()
        for role in ('latest', 'seasonal', 'target'):
            f = c[role]
            if f['issuer'] != c['issuer'] or not math.isfinite(f['val']) or f['val'] <= 0:
                raise ValueError('invalid_revenue_or_identity')
            available = date.fromisoformat(f['available'])
            if available != date.fromisoformat(f['filed']) + timedelta(days=1):
                raise ValueError('availability_convention_changed')
            if role != 'target' and (available > origin or f['end'] >= c['target']['start']):
                raise ValueError('feature_unavailable_at_origin')
            regimes.add(f['accounting_regime'])
        if len(regimes) != 1:
            raise ValueError('accounting_transition_straddled')
        if origin != date.fromisoformat(c['target']['start']) - timedelta(days=1):
            raise ValueError('origin_mismatch')
        if c['seasonal']['fy'] != c['target']['fy'] - 1 or c['seasonal']['fq'] != c['target']['fq']:
            raise ValueError('seasonal_period_mismatch')
    return lookup


def validate_fold(cases: list[dict], lookup: dict, fold: dict) -> tuple[dict, list[dict]]:
    if fold['lane'] not in LANES:
        raise ValueError('unknown_lane')
    test = lookup[fold['test_id']]
    if fold['origin'] != test['origin']:
        raise ValueError('fold_origin_mismatch')
    ids = fold['train_ids']
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate_training_case')
    expected = [c['id'] for c in cases
                if c['origin'] < test['origin'] and c['target']['available'] <= test['origin']
                and (fold['lane'] != LANES[1] or c['issuer'] != test['issuer'])]
    if set(ids) != set(expected) or len(ids) < 20:
        raise ValueError('training_admission_failed')
    return test, [lookup[i] for i in ids]


def predict(train: list[dict], test: dict) -> float:
    """Return revenue in USD millions; alpha=1, unpenalized intercept."""
    x = [c['seasonal']['val'] / c['latest']['val'] for c in train]
    y = [c['target']['val'] / c['latest']['val'] for c in train]
    mean, scale = statistics.mean(x), statistics.pstdev(x) or 1.0
    z = [(v - mean) / scale for v in x]
    intercept = statistics.mean(y)
    coefficient = sum(a * (b - intercept) for a, b in zip(z, y)) / (sum(a*a for a in z) + 1.0)
    feature = test['seasonal']['val'] / test['latest']['val']
    ratio = intercept + coefficient * (feature - mean) / scale
    return ratio * test['latest']['val'] / 1e6


def replay(cases: list[dict], split: dict) -> list[dict]:
    lookup = validate_cases(cases)
    rows, seen = [], set()
    for fold in split['folds']:
        key = (fold['lane'], fold['test_id'])
        if key in seen:
            raise ValueError('duplicate_evaluation_fold')
        seen.add(key)
        test, train = validate_fold(cases, lookup, fold)
        rows.append({'id': test['id'], 'issuer': test['issuer'], 'lane': fold['lane'],
                     'origin': test['origin'], 'target_end': test['target']['end'], 'n_train': len(train),
                     'actual': test['target']['val']/1e6,
                     'predictions': {'ridge': predict(train, test),
                                     'latest': test['latest']['val']/1e6,
                                     'seasonal': test['seasonal']['val']/1e6}})
    return rows


def metrics(rows: list[dict]) -> dict:
    scores = {}
    for lane in LANES:
        scores[lane] = {}
        for method in ('ridge', 'latest', 'seasonal'):
            per = {}
            for issuer in sorted({r['issuer'] for r in rows}):
                selected = [r for r in rows if r['lane'] == lane and r['issuer'] == issuer]
                errors = [abs(r['predictions'][method] - r['actual']) for r in selected]
                per[issuer] = {'n': len(selected), 'MAE_million': statistics.mean(errors),
                               'MAPE_percent': statistics.mean(e/r['actual']*100 for e, r in zip(errors, selected))}
            scores[lane][method] = {'per_issuer': per,
                                    'equal_issuer_MAE_million': statistics.mean(p['MAE_million'] for p in per.values()),
                                    'equal_issuer_MAPE_percent': statistics.mean(p['MAPE_percent'] for p in per.values())}
    return scores
