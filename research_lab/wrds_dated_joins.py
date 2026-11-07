"""Pure effective-date joins; matching never establishes historical availability.

Closed intervals follow the WRDS historical constituents example. Missing ends
are unresolved, never replaced with today's date. No I/O or capture mutation.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Sequence


@dataclass(frozen=True)
class DatedRecord:
    """One source interval; value is a membership label or dated identifier."""
    permno: int
    start: date
    end: date | None
    value: str
    source_ref: str

    def __post_init__(self) -> None:
        if type(self.permno) is not int or self.permno <= 0:
            raise ValueError('invalid_security_key')
        if type(self.start) is not date or (self.end is not None and type(self.end) is not date):
            raise ValueError('invalid_interval_date')
        if self.end is not None and self.end < self.start:
            raise ValueError('reversed_interval')
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError('missing_value')
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ValueError('missing_provenance')


@dataclass(frozen=True)
class IntervalMatch:
    status: Literal['matched', 'unmatched', 'ambiguous', 'unknown_end']
    candidates: tuple[DatedRecord, ...]


@dataclass(frozen=True)
class DatedJoin:
    permno: int
    on: date
    membership: IntervalMatch
    identifier: IntervalMatch
    backtest_eligible: bool = field(default=False, init=False)
    execution_allowed: bool = field(default=False, init=False)
    historical_available_at: None = field(default=None, init=False)


def match_interval(permno: int, on: date, records: Sequence[DatedRecord]) -> IntervalMatch:
    """Retain all possible matches, including duplicates and unknown ends.

    An unmatched result means no matching supplied interval, not proven absence
    from the index. Callers must separately establish source completeness.
    """
    if type(permno) is not int or permno <= 0 or type(on) is not date:
        raise ValueError('invalid_observation_key')
    candidates = tuple(sorted(
        (r for r in records if r.permno == permno and r.start <= on
         and (r.end is None or on <= r.end)),
        key=lambda r: (r.start, r.end or date.max, r.value, r.source_ref),
    ))
    if any(r.end is None for r in candidates):
        status = 'unknown_end'
    elif len(candidates) > 1:
        status = 'ambiguous'
    elif candidates:
        status = 'matched'
    else:
        status = 'unmatched'
    return IntervalMatch(status, candidates)


def join_membership_identifiers(
    observations: Sequence[tuple[int, date]],
    memberships: Sequence[DatedRecord],
    identifiers: Sequence[DatedRecord],
) -> tuple[DatedJoin, ...]:
    """One result per unique input key; never drop or multiply observations.

    Membership input must be scoped to one explicitly selected index. Identifier
    input must be scoped to one identifier kind. CCM policy is not inferred.
    """
    seen = set()
    results = []
    for permno, on in observations:
        membership = match_interval(permno, on, memberships)
        identifier = match_interval(permno, on, identifiers)
        if (permno, on) in seen:
            raise ValueError('duplicate_observation_key')
        seen.add((permno, on))
        results.append(DatedJoin(permno, on, membership, identifier))
    return tuple(results)
