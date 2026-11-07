# Portfolio Research Ontology

This package is a standalone, research-only authority for immutable ontology
records and their derived projections.

- Do not import from or resolve paths into Noesis, Obsidian, broker, execution,
  dashboard, or trading modules.
- Keep `ClaimVersion` as the atomic claim unit. Do not add a universal status;
  lifecycle, evidence, authority, decision, freshness, and admissibility remain
  independent.
- Canonical records are append-only. Graphs, indexes, current-state views, and
  context bundles are deterministic projections.
- Agents may propose records and run registered deterministic checks. They may
  not create human dispositions, promote authority, reinterpret data blockage
  as negative evidence, or enable execution.
- New methods, skills, verification rules, evaluation rubrics, and model-judge
  settings must be versioned and hash-bound to their run receipts.
- V0 does not pull live data, place trades, change portfolio exposure, or
  replace any existing Portfolio Management consumer.
