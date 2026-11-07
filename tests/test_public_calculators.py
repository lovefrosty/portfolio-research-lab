from fractions import Fraction
import json
import pytest

from examples.reconciliation_demo import prepare, run
from research_skill_lab.reconciliation_flat30 import compute_flat
from research_skill_lab.reconciliation_operands20 import compute_bound, digest

FIELD = 'same_period_revision_usd'
REQUEST = {FIELD: {'plan_id': FIELD}}


def test_demo_checks_both_representations_and_source_mutation():
    result = run()
    assert Fraction(result['graph_value_usd']) == 10_000_000
    assert result['changed_source_rejected_by'] == ['graph', 'flat']


@pytest.mark.parametrize('name,calculator', [('graph', compute_bound), ('flat', compute_flat)])
def test_caller_cannot_replace_formula_or_operands(tmp_path, name, calculator):
    pins = prepare(tmp_path)
    for extra in [{'formula': '0'}, {'operands': ['1', '2']}]:
        with pytest.raises(ValueError, match='literal_operands_or_formula_override_forbidden'):
            calculator({FIELD: {'plan_id': FIELD, **extra}}, tmp_path, pins[name])


@pytest.mark.parametrize('name,calculator,filename', [
    ('graph', compute_bound, 'lineage-graph.json'),
    ('flat', compute_flat, 'operand-ledger.json'),
])
def test_changed_plan_requires_new_trusted_pin(tmp_path, name, calculator, filename):
    pins = prepare(tmp_path)
    path = tmp_path / filename
    obj = json.loads(path.read_text())
    obj['plans'][FIELD]['formula'] = 'original-revised'
    path.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match='digest_mismatch'):
        calculator(REQUEST, tmp_path, pins[name])


def test_graph_rejects_semantically_wrong_period_even_with_new_digest(tmp_path):
    prepare(tmp_path)
    path = tmp_path / 'lineage-graph.json'
    obj = json.loads(path.read_text())
    obj['nodes']['original']['period'] = '2020-Q2'
    path.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match='operand_semantic_mismatch'):
        compute_bound(REQUEST, tmp_path, digest(path))
