from examples.dated_join_demo import run
from scripts.summarize_reconciliation import summarize


def test_report_aggregation():
    result = summarize()
    assert result['arms']['flat_bound']['uncached_input_tokens'] == 117181
    assert result['arms']['graph']['uncached_input_tokens'] == 147446


def test_effective_date_does_not_authorize_backtest():
    result = run()
    assert result['membership'] == result['identifier'] == 'matched'
    assert result['historical_available_at'] is None
    assert result['backtest_eligible'] is result['execution_allowed'] is False
