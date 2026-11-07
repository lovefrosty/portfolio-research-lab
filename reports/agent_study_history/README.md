# What changed after the reconciliation experiment?

**The later studies tested broader tasks, but they did not establish a general graph advantage or a ranking of different models.** This overview consolidates six historical studies that otherwise look like separate projects in the archive. It preserves unfavorable scores and changes in assistance rather than turning successive versions into a single improvement curve.

The [R31 reconciliation report](../reconciliation/README.md) is the starting case. Its constrained calculations were followed by revision-impact tasks, a shared deterministic planner, tool-use diagnostics, repeated company cases, bounded source discovery and a queryable company model. The important distinction is what the agent had to determine versus what the surrounding system had already computed.

## Historical evaluation results

| Study | Task and supplied assistance | Distinct evaluation cases | Flat full passes | Graph full passes | Main limit or failure |
|---|---|---:|---:|---:|---|
| R32 | Identify consequences of a source revision from supplied facts, typed relations and policy; no answer plan supplied | 6 synthetic | 1/6 | 1/6 | Neither arm passed an admitted source-change case. Reads often succeeded while date, dependency or structured-answer decisions failed. |
| R33 | Report a shared deterministic update plan derived from the supplied facts | 6 synthetic | 5/6 | 4/6 | Assisted reporting, not independent traversal. Three evaluation episodes made no required reads; the tool/model cause remained unresolved. |
| R34 | Report research-state changes with the shared planner and a revised tool interface/instructions | 6 synthetic | 6/6 | 6/6 | Bundled assistance and a small cohort; successful reporting does not establish unrestricted research reliability. |
| R35 | Interpret dated evidence for company assumptions, acquisition status and guidance; three sessions per case | 3 real company cases | 8/9 | 7/9 | Repetitions are not new company cases. Ambiguous rubric requirements and an unsupported interpretation remained. |
| R36 | Search and open documents within a curated six-document corpus; three sessions per issuer event | 2 real issuer events | 3/6 | 3/6 | Five rubric/task mismatches and one exact-quote formatting violation remained in the strict scores. |
| R37 | Query a company model and report deterministic calculations while preserving two explicit assumption branches | 1 historical issuer event | 2/3 | 1/3 | All six chose the checked numeric bindings, but three misdescribed the debt measurement basis. |

The denominators count episodes within each arm, not independent research observations. These studies requested GPT-6 Luna; provider-served identity was not independently attested. They compare graph and flat representations within constrained environments, not different model families.

## Why this is not a rising success-rate chart

R32 and R33 answer materially different questions. In R32, the agent determines the update's consequences. In R33, a deterministic planner supplies that result, and the agent must report it faithfully. A higher pass count after introducing the planner cannot be credited to graph representation or unaided reasoning.

R34 added explicit tool instructions and recorded protocol lifecycle. Its diagnostic probes observed four of four passes under the explicit configuration and three of four under the generic configuration. This was a small bundled intervention. It did not establish that one wording change caused the difference or retroactively explain earlier no-read failures.

R35–R37 move toward financial interpretation. Correct actions or numbers can coexist with incomplete or inaccurate explanations. R37 illustrates the distinction: selecting the correct debt number did not prevent an incorrect claim about whether issuance-cost adjustments were included. Source definitions were missing from the supplied context, which limits the instrument as well as the agent assessment.

R36 demonstrates why the evaluator deserves its own audit. A separate model review supported all twelve factual interpretations, while the frozen strict score remained six passes overall. Five failures came from requiring a particular historical evidence path beyond the decisive current source; another violated the exact-quote formatting rule. The secondary review was model-based, not independent human ground truth. The original scores remain visible rather than being silently replaced.

The [runnable evaluator audit](../evaluator_audit/README.md) provides separate synthetic counterexamples of measurement failures. It does not prove that every issue in these six studies has been corrected.

## What a reader can reproduce here

```sh
python3 -m scripts.summarize_agent_history
```

The command recomputes counts from [97 selected historical episode records](episode-summary.json), keeping study, phase and arm separate. Development, confirmation and tool-diagnostic records remain distinct from evaluation. Duplicate episode identifiers and non-boolean pass flags are rejected. There is no pooled success-rate output.

For this publication, those records were extracted from saved result tables and checked against each study's saved aggregates. [Provenance](provenance.json) records the source-file hashes and exported fields. No new inference or semantic regrading was performed. The metadata contains no private task inputs, raw model answers, source captures or traces.

This is an archival overview, not six complete replay packages. A reader can reproduce the displayed counts but cannot independently rerun the original source checks or review judgments from these files alone. The counts do not measure forecast outcomes, investment returns or preparation/review labor. No general efficiency ranking follows from them.

## How this directs further work

The next revision-impact collaboration should build on these recorded attempts: challenge the planner and evaluator on held-back cases, separate plan computation from faithful reporting, and account for tool exposure failures. Another graph-versus-table run should state which previously unresolved mechanism it tests.

For a discussion or demonstration, start with one task and show the supplied evidence, the agent's permitted choices, the expected result and one retained failure. This is a more inspectable contribution than a large architecture diagram or a success percentage pooled across changing tasks.
