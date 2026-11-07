# Presenting the work

These are suggested descriptions to adapt after inspecting the linked examples. They describe the published evidence, not a certification of the owner's unaided understanding. The project is AI-assisted; implementation and research decisions should be attributed specifically when discussing them.

## A short introduction

> I'm building an AI-assisted lab for evaluating agents on defined financial-research tasks. Financial reconciliation gives me a way to inspect sources, calculations and failure conditions. I've published a small graph-versus-table comparison, reproducible evaluator failures and a revenue model that did not beat a simple baseline overall.

The [PAT inspiration note](PAT_INSPIRATION.md) explains the influence of Bridgewater's presentation. This project does not claim to reproduce PAT or its results.

## Three demonstrations to understand

| Demonstration | What to explain | What remains unproven |
|---|---|---|
| [Reconciliation](../reports/reconciliation/README.md) | Follow one field from bound source values through a fixed formula. Explain which choices the agent made and which work the controller supplied. Show a changed source being rejected. | Four paired passes do not establish graph superiority or general analyst reliability. |
| [Evaluator audit](../reports/evaluator_audit/README.md) | Show why absent files produce no recorded mismatch in the historical verifier, then why that does not justify calling the evidence verified. | Reproducing a weakness does not establish its frequency or historical exploitation. |
| [Forecasting](../reports/revenue_forecasting/README.md) | Reconstruct one dated forecast, compare both simple baselines, and explain why 48 fits reuse only 24 outcomes. | Numerical reconstruction does not establish exact historical availability or predictive generalization. |

For the date question, the decisive issue is when information became available. A later revised number can be better measured yet still be unavailable to the original forecaster. Conversely, a study can explicitly choose a revised outcome as its target; that does not permit using future revisions as historical inputs.

The [later-study history](../reports/agent_study_history/README.md) is useful when someone asks how the work evolved. Explain why supplying a deterministic answer plan changes the task before discussing changes in pass counts.

## Suggested short post

> Building an AI-assisted lab for financial-agent evaluation. Published: graph vs table reconciliation, five reproducible evaluator failures, and a revenue model that loses to a simple baseline overall. Code, evidence and limits: https://github.com/lovefrosty/portfolio-research-lab

## Suggested email introduction

> I've been working on evaluating AI agents on narrowly defined financial-research tasks, especially reconciliation and source-based reasoning. My public repository contains runnable examples, retained failures and explicit limits on the conclusions. I'd welcome feedback on task design, evaluator validity or a controlled comparison using new cases.

Link: [Portfolio Research Lab](https://github.com/lovefrosty/portfolio-research-lab).

These are drafts only. No social post, email or outreach has been sent by this repository's publication workflow.
