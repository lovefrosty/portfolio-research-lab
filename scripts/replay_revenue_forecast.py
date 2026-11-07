"""Reproduce the published 48 fits and compare with saved historical predictions."""
import json
from pathlib import Path

from research_lab.revenue_forecast import metrics, replay

REPORT = Path(__file__).resolve().parents[1]/'reports/revenue_forecasting'


def run() -> dict:
    cases = json.loads((REPORT/'cases.json').read_text())
    split = json.loads((REPORT/'frozen-split.json').read_text())
    saved = json.loads((REPORT/'predictions.json').read_text())
    rows = replay(cases, split)
    old = {(r['lane'], r['id']): r for r in saved}
    if len(old) != len(saved) or {(r['lane'], r['id']) for r in rows} != set(old):
        raise ValueError('saved_prediction_set_mismatch')
    discrepancies = []
    for row in rows:
        previous = old[row['lane'], row['id']]
        for field in ('issuer', 'origin', 'target_end', 'n_train', 'actual'):
            if row[field] != previous[field]:
                raise ValueError('saved_metadata_mismatch:' + field)
        for method in ('ridge', 'latest', 'seasonal'):
            discrepancies.append(abs(row['predictions'][method] - previous['predictions'][method]))
    maximum = max(discrepancies)
    if maximum > 1e-8:
        raise ValueError('numerical_reconstruction_mismatch')
    if len(cases) != 68 or len(rows) != 48 or len({r['id'] for r in rows}) != 24:
        raise ValueError('published_case_count_changed')
    scores = metrics(rows)
    if any(p['n'] != 8 for lane in scores.values() for method in lane.values() for p in method['per_issuer'].values()):
        raise ValueError('published_issuer_coverage_changed')
    return {'cases': len(cases), 'fits': len(rows), 'unique_evaluation_outcomes': 24,
            'maximum_difference_USD_million': maximum, 'scores': scores,
            'scope': 'Numerical replay of admitted cases. No new forecasts, source acquisition or model selection.',
            'exact_historical_availability_verified': False, 'protected_holdout': False}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, allow_nan=False))
