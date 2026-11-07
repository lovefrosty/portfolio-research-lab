"""Compare the retained graph and flat calculators on invented source evidence.

Run from the repository root: python3 -m examples.reconciliation_demo
The example writes only to a disposable temporary directory.
"""
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from research_skill_lab.reconciliation_flat30 import compute_flat
from research_skill_lab.reconciliation_operands20 import compute_bound, digest


def prepare(root: Path) -> dict[str, str]:
    """Create fictional, same-period original/revised revenue and pinned plans."""
    source = root / 'synthetic-source.txt'
    source.write_text(
        'SYNTHETIC EXAMPLE: invented company and amounts; USD millions.\n'
        'L1: Original revenue | 100\n'
        'L2: Revised revenue | 110\n', encoding='utf-8')
    nodes = {}
    for role, line, amount in [('original', 1, '100'), ('revised', 2, '110')]:
        nodes[role] = {
            'kind': 'source_observation', 'issuer': 'SYNTHETIC_CO',
            'source_file': source.name, 'source_sha256': digest(source),
            'line': line, 'numeric_index': 0, 'reviewed_value': amount,
            'source_unit': 'USD_millions', 'metric': 'revenue',
            'period': '2020-Q1', 'vintage': role, 'canonical_assertion': None,
        }
    field = 'same_period_revision_usd'
    plan = {
        'node_id': field, 'authority': 'controller_reviewed_calculation',
        'issuer': 'SYNTHETIC_CO', 'formula': 'revised-original', 'unit': 'USD',
        'operands': {'original': 'original', 'revised': 'revised'},
        'operand_contracts': {
            role: {'metric': 'revenue', 'period': '2020-Q1', 'vintage': role}
            for role in nodes
        },
    }
    graph = {
        'nodes': nodes, 'plans': {field: plan},
        'edges': [{'from': role, 'to': field, 'relation': 'operand_of', 'role': role}
                  for role in nodes],
        'authority': 'synthetic_demonstration', 'canonical_graph_status': 'unlinked',
        'execution_allowed': False,
    }
    flat = {'plans': {field: {
        'formula': plan['formula'], 'unit': 'USD', 'issuer': plan['issuer'],
        'operands': nodes,
    }}, 'execution_allowed': False}
    for name, obj in [('lineage-graph.json', graph), ('operand-ledger.json', flat)]:
        (root / name).write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')
    return {'graph': digest(root / 'lineage-graph.json'),
            'flat': digest(root / 'operand-ledger.json')}


def run() -> dict:
    field = 'same_period_revision_usd'
    request = {field: {'plan_id': field}}
    with TemporaryDirectory(prefix='reconciliation-demo-') as tmp:
        root = Path(tmp)
        pins = prepare(root)
        graph = compute_bound(request, root, pins['graph'])[field]
        flat = compute_flat(request, root, pins['flat'])[field]
        # Different numeric representation, independently stated arithmetic.
        expected = (Fraction(110) - Fraction(100)) * 1_000_000
        assert Fraction(graph['value']) == Fraction(flat['value']) == expected
        source = root / 'synthetic-source.txt'
        source.write_text(source.read_text().replace('110', '111'))
        rejected = []
        for name, calculator in [('graph', compute_bound), ('flat', compute_flat)]:
            try:
                calculator(request, root, pins[name])
            except ValueError as error:
                assert str(error) == 'source_hash_mismatch'
                rejected.append(name)
        assert rejected == ['graph', 'flat']
        return {
            'evidence': 'synthetic', 'calculation': '(110 - 100) million USD',
            'graph_value_usd': graph['value'], 'flat_value_usd': flat['value'],
            'independent_fraction_value_usd': str(expected),
            'changed_source_rejected_by': rejected,
            'interpretation': 'A same-period revision, not revenue growth or a forecast.',
            'execution_allowed': False,
        }


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
