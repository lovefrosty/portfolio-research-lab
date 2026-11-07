import json
import pytest

from scripts.summarize_agent_history import SOURCE,summarize


def test_repetitions_are_not_distinct_cases():
    groups=summarize(json.loads(SOURCE.read_text()))
    row=next(r for r in groups if r['study']=='R35' and r['arm']=='flat')
    assert row['episodes']==9 and row['distinct_cases']==3
    assert row['historical_full_passes']==8
    assert any(r['phase']=='diagnostic' for r in groups)


def test_duplicate_episode_rejected():
    row=json.loads(SOURCE.read_text())[0]
    with pytest.raises(ValueError,match='duplicate_episode'):
        summarize([row,row.copy()])


def test_string_false_cannot_be_counted_as_true():
    row=json.loads(SOURCE.read_text())[0]
    row['full_pass']='False'
    with pytest.raises(ValueError,match='must_be_boolean'):
        summarize([row])
