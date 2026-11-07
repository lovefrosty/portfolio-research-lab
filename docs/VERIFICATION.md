# Release verification

Local check, November 7, 2026: **122 tests passed** using a new Python 3.13 virtual environment and the pinned `pytest==8.3.5` dependency.

| Evidence | Scope |
|---|---|
| 73 retained ontology tests | Contracts, policy, ledger, projection and independent verifier on synthetic fixtures |
| 37 retained research-method tests | Synthetic effective-date joins and numerical momentum boundaries |
| 8 public example/report tests | Source-bound arithmetic, prohibited overrides, source/plan changes, aggregate metrics and false backtest eligibility |
| 4 publication-check tests | Reject unexpected files, changed bytes, broken local links and symlinks |
| Three documented commands | Synthetic reconciliation, synthetic dated joins and historical-metadata aggregation all executed successfully |
| Gitleaks 8.30.1 | Candidate scan detected no secrets; scanner archive matched its published SHA-256 |
| Content inspection | Selected text reviewed for personal paths, account information, data payloads and source attribution; synthetic fixture email uses an example domain |

Tests do not run model inference, call data providers, access personal accounts or establish investment performance. The historical report's `focused_tests_passed: 59` describes its original study; it is not this edition's test count.

Reproduce checks from the root:

```sh
python3 -m scripts.check_release
python3 -m pytest -q
python3 -m examples.reconciliation_demo
python3 -m examples.dated_join_demo
python3 -m scripts.summarize_reconciliation
```

The checked-in manifest lists exactly the publication files and their hashes, excluding itself. It supports integrity and scope checks, not authenticity or data-rights certification. Development caches are excluded, and tracked files must match the manifest once the repository is initialized.

The GitHub workflow runs tests and examples on Python 3.10 and 3.12. Its status is separate evidence from the local run. The ledger uses POSIX file locking; Windows behavior has not been validated.

The full historical reconciliation experiment is not independently reproducible from this edition because original prompts, captures, keys and traces are excluded. The published aggregates and synthetic mechanism are reproducible. See the [case study](../reports/reconciliation/README.md) for the limitations of historical review evidence.
