"""Regression coverage for an audit specimen, not a corrected evaluator."""
import hashlib
import json

from examples.evaluator_audit_demo import run, synthetic_record
from reports.evaluator_audit.specimens import gate, manifest


def test_five_false_acceptances_reproduce():
    result = run()
    assert {c['id'] for c in result['cases']} == {'C1', 'C2', 'C3', 'C4', 'C5'}
    assert result['reproduced'] == result['total'] == 5
    assert all(c['weakness_reproduced'] for c in result['cases'])
    json.dumps(result, allow_nan=False)


def test_manifest_accepts_matching_file_and_detects_changed_file(tmp_path):
    source = tmp_path/'source.txt'
    source.write_text('original fixture')
    record = {'task': {'prompt': str(source),
                       'prompt_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}}
    assert manifest.verify(record)['verified'] is True
    source.write_text('changed fixture')
    result = manifest.verify(record)
    assert result['verified'] is False
    assert 'task.prompt_sha256' in result['drift']


def test_gate_positive_control_and_null_threshold_rejection(tmp_path):
    path = tmp_path/'hypothesis.json'
    record = synthetic_record()
    path.write_text(json.dumps(record))
    assert gate.check(path) == []
    record['kill_criterion']['metrics'] = [{'name': 'synthetic_error', 'threshold': None}]
    path.write_text(json.dumps(record))
    assert any('no numeric threshold' in p for p in gate.check(path))
