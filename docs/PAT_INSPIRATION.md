# PAT inspiration and the question this project tests

The project owner identifies Bridgewater's PAT presentation as an inspiration for testing agents on defined financial research tasks. This is an attribution of influence, not an affiliation, reproduction of PAT, or validation of its reported results.

In [the LangChain presentation](https://www.youtube.com/watch?v=lXZb21CfeIY), the speakers describe separating research planning from code generation and execution. Around 20:24–21:06, they discuss specifying calculations and expected output structure; around 21:46–22:42, they describe checking execution against the task. Around 24:25–24:54, they advocate specializing and benchmarking narrower workflows before composing them. These references were checked against a locally retained transcript; timestamps are approximate.

The idea carried into this project is to make a task, its permitted evidence, and its success conditions explicit enough to inspect failures. PAT's internal repeatability statement is not a benchmark result for this repository, and repeated agreement would not by itself establish financial correctness.

## What the published experiment actually tests

The [R31 reconciliation study](../reports/reconciliation/README.md) compares a graph configuration with a source-bound flat-table configuration on four paired financial reconciliation cases. Both requested the same model. Evidence selection, formulas and narrative templates were substantially prepared by the surrounding system.

Unlike the presentation's code-generation workflow, this study restricted the agent to scoped reading and fixed calculation tools. The result is evidence about behavior inside that constrained task, not autonomous financial research or trading performance. Both configurations passed; no graph accuracy advantage was demonstrated.

## A concrete next collaboration

The [later-study history](../reports/agent_study_history/README.md) records revision-impact attempts already made after R31. A new collaboration should address their unresolved measurement and assistance boundaries rather than treat this as an untested idea.

Use a source revision to ask which reported conclusions must change. Freeze the source bundle, required outputs and independently reviewed expected answers before inference. Challenge the evaluator with wrong-period, wrong-unit, unsupported-claim and missing-evidence cases before trusting candidate scores.

To compare models, hold the task, tools and evaluator fixed. To compare representations, hold the requested model fixed and account for differences in tool capabilities and preparation effort. Repeated attempts, failures, missing identities, review labor and uncertain costs belong in the record. This is a proposed study, not a completed result.
