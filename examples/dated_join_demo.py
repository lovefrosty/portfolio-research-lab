"""Synthetic example: effective dates do not establish information availability."""
from datetime import date
import json

from research_lab.wrds_dated_joins import DatedRecord, join_membership_identifiers


def run() -> dict:
    membership = DatedRecord(1, date(2020, 1, 1), date(2020, 12, 31),
                             'SYNTHETIC_INDEX', 'synthetic:membership')
    name = DatedRecord(1, date(2020, 1, 1), date(2020, 12, 31),
                      'SYNTHETIC_NAME', 'synthetic:identifier')
    result = join_membership_identifiers([(1, date(2020, 6, 30))],
                                         [membership], [name])[0]
    return {
        'evidence': 'synthetic', 'membership': result.membership.status,
        'identifier': result.identifier.status,
        'historical_available_at': result.historical_available_at,
        'backtest_eligible': result.backtest_eligible,
        'execution_allowed': result.execution_allowed,
        'interpretation': 'Matching effective dates does not prove when the record became known.',
    }


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
