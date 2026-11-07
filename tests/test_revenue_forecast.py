import copy
from fractions import Fraction
import json

import pytest

from research_lab.revenue_forecast import predict, replay, validate_cases, validate_fold
from scripts.replay_revenue_forecast import REPORT, run


def load():
    return (json.loads((REPORT/'cases.json').read_text()),
            json.loads((REPORT/'frozen-split.json').read_text()))


def test_all_saved_fits_and_baseline_ordering():
    result = run()
    assert result['fits'] == 48 and result['unique_evaluation_outcomes'] == 24
    scores = result['scores']['pooled_expanding']
    assert scores['latest']['equal_issuer_MAPE_percent'] < scores['ridge']['equal_issuer_MAPE_percent']


def test_ridge_matches_hand_calculated_normal_equations():
    def case(x, y):
        return {'latest': {'val': 10_000_000}, 'seasonal': {'val': x*10_000_000},
                'target': {'val': y*10_000_000}}
    # x=(.5,1.5) gives z=(-1,1); y=(1,3), intercept=2,
    # penalized slope=2/(2+1). At z=1, revenue=10*(2+2/3).
    assert predict([case(.5, 1), case(1.5, 3)], case(1.5, 0)) == pytest.approx(float(Fraction(80, 3)))
    assert predict([case(1, 2), case(1, 2)], case(1, 0)) == 20.0


def test_feature_released_after_origin_is_rejected():
    cases, _ = load()
    c = cases[0]
    c['latest']['filed'] = c['origin']
    from datetime import date, timedelta
    c['latest']['available'] = (date.fromisoformat(c['origin'])+timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match='feature_unavailable'):
        validate_cases(cases)


def test_training_label_unavailable_at_origin_is_rejected():
    cases, split = load()
    lookup = validate_cases(cases)
    fold = split['folds'][0]
    lookup[fold['train_ids'][0]]['target']['available'] = '2099-01-01'
    with pytest.raises(ValueError, match='training_admission'):
        validate_fold(cases, lookup, fold)


def test_held_out_issuer_cannot_enter_training():
    cases, split = load()
    lookup = validate_cases(cases)
    fold = next(f for f in split['folds'] if f['lane'] == 'leave_one_issuer_out_expanding')
    target = lookup[fold['test_id']]
    donor = next(c for c in cases if c['issuer'] == target['issuer'] and c['target']['available'] <= target['origin'])
    fold['train_ids'].append(donor['id'])
    with pytest.raises(ValueError, match='training_admission'):
        validate_fold(cases, lookup, fold)


def test_duplicate_fold_and_accounting_transition_are_rejected():
    cases, split = load()
    split['folds'].append(copy.deepcopy(split['folds'][0]))
    with pytest.raises(ValueError, match='duplicate_evaluation_fold'):
        replay(cases, split)
    cases[0]['latest']['accounting_regime'] = 'different-regime'
    with pytest.raises(ValueError, match='accounting_transition'):
        validate_cases(cases)
