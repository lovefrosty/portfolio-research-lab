# Publication boundaries

The public repository starts with fresh history and an explicit file selection. It is not a visibility change or history-preserving copy of the private operational repository.

Included material: selected Python methods and synthetic tests; newly authored documentation and demonstrations; allowlisted historical reconciliation evaluation metadata; historical evaluator code excerpts with invented inputs; admitted public SEC revenue cases, frozen splits and saved forecasts; artifact hashes and public filing links. Hashes support byte identity, not authenticity or semantic correctness.

Excluded material: credentials, environment files, account identifiers, holdings, private datasets, WRDS observations, vendor-derived row exports, databases, unrestricted prompts and traces, raw captures, private absolute paths, caches and original Git history.

WRDS-related methods here have no data access functions. Fixtures are invented. An empirical aggregate is not automatically cleared for publication because raw rows were removed. Review the applicable vendor and institution agreement for each proposed result. Reference pages: [WRDS data handling and AI policy](https://wrds-www.wharton.upenn.edu/pages/about/ai-policy-on-chatgpt-and-other-generative-ai-tools/) and [data sharing guidance](https://wrds-www.wharton.upenn.edu/pages/about/navigating-co-authorship-across-institutions-a-guide-to-data-sharing-and-compliance/).

## Adding a report

1. Identify the question and preserve relevant attempts, including losses and failed reviews.
2. Classify each file by origin, contents and redistribution basis. Exclude unknown material.
3. Inspect text, notebook outputs, attachments, charts, URLs and embedded data. Extensions alone are insufficient.
4. Use labeled synthetic examples when observations cannot be redistributed; separate them from empirical findings.
5. Reproduce published calculations in a clean copy. State explicitly if the historical experiment cannot be replayed.
6. Scan the exact staged files and history for secrets and review dataset/privacy risks separately. Commit only the reviewed selection.

`scripts/check_release.py` verifies the file manifest, rejects unexpected files and obvious private paths, and validates local Markdown targets. It does not prove data rights or replace a secret scanner. Caches and development environments are not release artifacts.

Research-only flags remain false for execution. Tests and a public page do not authorize trading or establish production readiness.
