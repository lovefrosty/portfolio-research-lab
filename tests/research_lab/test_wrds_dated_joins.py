"""Synthetic only: no licensed observations, network, or capture access."""
from datetime import date, datetime
from dataclasses import FrozenInstanceError
import pytest
from research_lab.wrds_dated_joins import DatedRecord, match_interval, join_membership_identifiers


def d(day):
    return date(2020, 2, day)


def r(start=3, end=6, value='SYNTHETIC', permno=1, ref='fixture:1'):
    return DatedRecord(permno, d(start), None if end is None else d(end), value, ref)


@pytest.mark.parametrize('day,expected', [(2,'unmatched'),(3,'matched'),(6,'matched'),(7,'unmatched')])
def test_closed_boundaries(day, expected):
    assert match_interval(1, d(day), [r()]).status == expected


def test_name_change_and_reused_ticker_do_not_change_security_identity():
    names = [r(1,4,'OLD'),r(5,9,'NEW'),r(1,9,'NEW',2)]
    out = join_membership_identifiers([(1,d(4)),(1,d(5))], [r(1,9)], names)
    assert [x.identifier.candidates[0].value for x in out] == ['OLD','NEW']
    assert all(len(x.identifier.candidates) == 1 for x in out)


def test_exit_gap_reentry_retains_every_observation():
    out = join_membership_identifiers([(1,d(x)) for x in (3,4,5,6)],
                                      [r(1,3),r(6,9)], [r(1,9)])
    assert [x.membership.status for x in out] == ['matched','unmatched','unmatched','matched']
    assert len(out) == 4


@pytest.mark.parametrize('records', [[r(),r()], [r(1,4),r(4,8)]])
def test_duplicates_and_touching_closed_intervals_are_ambiguous(records):
    result = match_interval(1,d(4),records)
    assert result.status == 'ambiguous'
    assert len(result.candidates) == 2


def test_missing_identifier_does_not_erase_membership():
    out = join_membership_identifiers([(1,d(4))], [r()], [r(5,8)])[0]
    assert out.membership.status == 'matched'
    assert out.identifier.status == 'unmatched'


def test_unknown_end_blocks_resolution_and_preserves_null():
    record = r(end=None)
    out = match_interval(1,d(4),[r(),record])
    assert out.status == 'unknown_end'
    assert len(out.candidates) == 2 and record.end is None
    assert match_interval(1,d(2),[record]).status == 'unmatched'


def test_future_records_and_input_order_do_not_change_earlier_match():
    base = [r()]
    expected = join_membership_identifiers([(1,d(4))],base,base)
    changed = [r(8,9,'FUTURE'),*base]
    assert join_membership_identifiers([(1,d(4))],changed,changed[::-1]) == expected


def test_provenance_and_false_gates_survive_success():
    member, name = r(ref='fixture:membership'), r(value='NAME',ref='fixture:name')
    out = join_membership_identifiers([(1,d(4))],[member],[name])[0]
    assert out.membership.candidates == (member,)
    assert out.identifier.candidates == (name,)
    assert out.backtest_eligible is False and out.execution_allowed is False
    assert out.historical_available_at is None
    with pytest.raises(FrozenInstanceError):
        out.backtest_eligible = True


@pytest.mark.parametrize('kwargs', [dict(start=6,end=3),dict(permno=True),dict(permno=1.0),dict(value=''),dict(ref='')])
def test_invalid_intervals_fail_without_echoing_inputs(kwargs):
    with pytest.raises(ValueError):
        r(**kwargs)


@pytest.mark.parametrize('on', [None,'2020-02-04',datetime(2020,2,4)])
def test_dates_require_explicit_normalization(on):
    with pytest.raises(ValueError,match='invalid_observation_key'):
        match_interval(1,on,[r()])


def test_duplicate_observation_rejected_not_double_weighted():
    with pytest.raises(ValueError,match='duplicate_observation_key'):
        join_membership_identifiers([(1,d(4)),(1,d(4))],[r()],[r()])


def test_empty_observations_are_empty_not_proof_of_coverage():
    assert join_membership_identifiers([],[],[]) == ()
