# Portfolio Research Lab

**Reproducible financial research, source-bound calculations, and tools for testing what the evidence supports.**

This project investigates how financial information becomes a research result: which version of a filing was available, what a number measures, how it was transformed, and whether a more elaborate method improves on a simple baseline.

It grew out of a broader portfolio-management workspace. This public edition brings together selected methods, a worked experiment and runnable examples. The [research map](docs/RESEARCH_MAP.md) explains the wider scope and distinguishes included tools from work awaiting publication.

## Start with the result

**[Does a graph improve financial reconciliation?](reports/reconciliation/README.md)**

In four paired cases, a graph and an equally source-bound flat table both passed. The graph showed no accuracy advantage and consumed more uncached input tokens. The case study explains the comparison, preserves the preceding failed review, and identifies what the result cannot establish.

The central question is how to evaluate an agent on a defined financial task, including whether its evaluator can distinguish a correct answer from convincing but unsupported output. The [PAT inspiration note](docs/PAT_INSPIRATION.md) explains the motivation and the narrower scope of this experiment.

The calculation reads reviewed source cells, checks their hashes and units, and accepts a field identifier instead of model-supplied numbers. Both representations can use those controls.

**[Can the evaluator tell evidence from an assertion?](reports/evaluator_audit/README.md)**

Five synthetic counterexamples reproduce false acceptances involving missing provenance, writable receipts, duplicated attempts, unread citations and a nonfinite threshold. The offline demonstration preserves historical evaluator behavior and compares it with explicit expected outcomes.

## Run a five-minute example

Python 3.10+ on macOS or Linux. Run from the repository root. These examples use only the standard library, require no credentials, and make no network requests.

```sh
python3 -m examples.reconciliation_demo
python3 -m examples.dated_join_demo
python3 -m examples.evaluator_audit_demo
python3 -m scripts.summarize_reconciliation
```

The first calculates an invented $10 million revision with both representations, checks it using rational arithmetic, and rejects a changed source. The second shows why matching effective dates does not prove historical information availability. The third reproduces five evaluator weaknesses using invented inputs. The fourth recomputes descriptive totals from historical experiment metadata; it does not rerun the model experiment.

To run the tests in an isolated environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

## What is here

| Component | Question it helps answer | Entry point |
|---|---|---|
| Financial reconciliation | Which source values, units and formula produced this answer? | [Example](examples/reconciliation_demo.py), [case study](reports/reconciliation/README.md) |
| Research ontology | Is a claim supported, reviewed, current and admissible? These are separate questions. | [Contracts](research_ontology/contracts.py), [ledger](research_ontology/ledger.py), [projections](research_ontology/projection.py) |
| Dated research joins | Which interval matches, and what remains unknown? | [Method](research_lab/wrds_dated_joins.py), [tests](tests/research_lab/test_wrds_dated_joins.py) |
| Numerical diagnostics | Can a rounding boundary change the sign of a flat price move? | [Boundary rule](research_lab/momentum_boundary.py), [tests](tests/research_lab/test_momentum_boundary.py) |
| Research review | What should be checked before sharing a result? | [Review skill](skills/review-research-result/SKILL.md) |

The ontology retains its larger contract vocabulary so the selected ledger and validation tests remain meaningful. Its 73 tests check specified software behavior on fixtures; they do not establish improved research accuracy or investment performance. It is supporting infrastructure, not a required framework for every small analysis. Historical module names are retained for provenance; the examples provide a short route into the code.

## Work with this project

Useful next investigations include a fair graph-versus-table comparison for revision-impact queries, independent reconstruction of a financial calculation, and review of effective dates versus availability dates. See [contribution notes](docs/CONTRIBUTIONS.md).

This is an AI-assisted project. Passing tests and generated explanations do not establish the owner's understanding. Implementation evidence, historical results and questions still being learned remain distinct.

Private datasets, WRDS observations, personal holdings, credentials and the original Git history are excluded. Examples are synthetic; experimental metrics are separately labeled. See [publication boundaries](docs/PUBLICATION.md) and [release checks](docs/VERIFICATION.md).

Research outputs do not authorize trading. No broker execution adapters or open-source license grant are included in this edition.
