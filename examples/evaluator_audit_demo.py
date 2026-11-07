"""Five synthetic counterexamples against preserved historical evaluator code.

No agents, credentials, network calls or historical task data. Temporary files
are deleted on exit. A successful demonstration reproduces evaluator weaknesses;
it does not mean the evaluator is safe or that an agent exploited them.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

from reports.evaluator_audit.specimens import aggregate, gate, grader, manifest, trace


def synthetic_record() -> dict:
    """An invented schema fixture, not a financial hypothesis or data export."""
    return {
        'hypothesis': 'The invented method will beat the invented baseline on held-out synthetic cases.',
        'mechanism': 'Fixture only: a deterministic rule on generated numbers.',
        'kill_criterion': {'text': 'Stop if synthetic error exceeds one.',
                           'metrics': [{'name': 'synthetic_error', 'maximum': 1.0}]},
        'horizon': 'one synthetic step',
        'cost_model': {'id': 'synthetic-zero', 'evidence_kind': 'assumption',
                       'fee_bps': 0, 'spread_bps': 0, 'slippage_bps': 0},
        'verdict_scale': 'pass/fail',
        'holdout_access_declared': False,
        'preregistered_at': '2026-01-01T00:00:00Z',
        'first_data_read_at': '2026-01-02T00:00:00Z',
        'preregistration_basis': 'before_data',
    }


def run_in(work: Path, modules=None) -> dict:
    # Dependency injection allows local comparison against original modules.
    m = modules or SimpleNamespace(manifest=manifest, aggregate=aggregate,
                                    trace=trace, grader=grader, gate=gate)
    cases = []
    missing = work/'absent-input.json'
    record = {'task': {'prompt': str(missing), 'prompt_sha256': '0'*64,
                       'data_sha256': {str(missing): '0'*64}},
              'evaluator': {'rubric_sha256': {str(work/'absent-rubric.py'): '0'*64}}}
    result = m.manifest.verify(record)
    cases.append({'id': 'C1', 'expected': 'Unverifiable: required files are absent.',
                  'observed': result,
                  'weakness_reproduced': result == {'verified': True, 'drift': {}}})

    task = work/'task'; task.mkdir()
    candidate = work/'candidate'; candidate.mkdir()
    # The original audit copied an existing submission. This public edition
    # authors a new synthetic submission and brief; neither contains private data.
    gate_bytes = Path(m.gate.__file__).read_bytes()
    for folder in (task, candidate):
        (folder/'gate.py').write_bytes(gate_bytes)
        (folder/'BRIEF.md').write_text('Synthetic fixture: return a preregistration record.\n')
    submission = candidate/'hypothesis.json'
    submission.write_text(json.dumps(synthetic_record()))
    assert m.gate.check(submission) == [], 'synthetic positive control must pass'
    receipt = {'status': 'pass',
               'artifact_sha256': hashlib.sha256(submission.read_bytes()).hexdigest(),
               'gate_source_sha256': hashlib.sha256(gate_bytes).hexdigest()}
    (candidate/'gate_receipt.json').write_text(json.dumps(receipt))
    log = candidate/'transcript.log'
    log.write_text('Controlled fixture: no agent or gate command was run.\n')
    result = m.grader.grade_cell(candidate, task, log, returncode=0)
    cases.append({'id': 'C2', 'expected': 'Artifact can pass; agent invocation is unverified.',
                  'observed': {'verdict': result['verdict'],
                               'receipt_accepted': result['trace']['gate_receipt'],
                               'agent_gate_invocations': 0},
                  'weakness_reproduced': result['verdict'] == 'pass' and result['trace']['gate_receipt']})

    row = {'harness': 'synthetic', 'model_requested': 'no-model',
           'provider_requested': 'no-provider', 'workspace': 'one-attempt',
           'task': 'one-task', 'protocol': {'repetition': 1},
           'result': {'combined_verdict': 'pass'}}
    result = next(iter(m.aggregate.pass_hat_k([copy.deepcopy(row) for _ in range(3)], 3).values()))
    cases.append({'id': 'C3', 'expected': 'Three-trial reliability unavailable from one unique attempt.',
                  'observed': {'reported_trials': result['trials'], 'unique_attempts': 1,
                               'reported_pass_hat_k': result['pass_hat_k']},
                  'weakness_reproduced': result['trials'] == 3 and result['pass_hat_k'] == 1.0})

    # Build a nonexistent absolute path recognized by the historical parser.
    # This is an invented name, never opened; it is not a local user path.
    invented = '/' + '/'.join(('Users', 'synthetic-fixture', 'never-opened-source.md'))
    citation_log = work/'citation.log'
    citation_log.write_text('Final answer cites ' + invented + '\n')
    facts = m.trace.parse_trace(citation_log)
    result = m.trace.score_trace(facts, workspace=None, required_artefact=None, task_inputs=[])
    citation = next(i for i in result['items'] if i['item'] == 'citations_were_read')
    cases.append({'id': 'C4', 'expected': 'Citation alone does not establish a source read.',
                  'observed': {'citation_accepted_as_read': citation['pass'],
                               'read_markers': facts.markers['read'], 'shell_markers': facts.markers['shell']},
                  'weakness_reproduced': citation['pass'] and facts.markers['read'] == facts.markers['shell'] == 0})

    bad = synthetic_record()
    bad['kill_criterion']['metrics'] = [{'name': 'synthetic_error', 'threshold': float('nan')}]
    invalid = work/'nonfinite.json'
    # Python JSON accepts NaN by default, although strict JSON forbids it.
    invalid.write_text(json.dumps(bad))
    problems = m.gate.check(invalid)
    cases.append({'id': 'C5', 'expected': 'Reject a nonfinite numeric threshold.',
                  'observed': {'gate_problem_count': len(problems), 'nonfinite_thresholds': 1},
                  'weakness_reproduced': problems == []})
    return {'scope': 'Synthetic counterexamples; no model trials or historical exploitation claim.',
            'reproduced': sum(c['weakness_reproduced'] for c in cases), 'total': len(cases), 'cases': cases}


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix='public-evaluator-audit-') as tmp:
        return run_in(Path(tmp))


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(0 if result['reproduced'] == result['total'] == 5 else 1)
