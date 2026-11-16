# URS AI REPORT SYSTEM — persistent working instructions

Read docs/HANDOFF.md and docs/checklist.md before continuing work.

- The user requires completion of all non-API development, with a checklist, real checks and reviewable evidence BEFORE advancing each stage. Do not stop after a plan or a dependency install.
- API secret binding/live authentication/billing setup is explicitly deferred. Do not repeat key checks, source changes, personal/shared toggles, screenshots or key-entry requests. The user has already saved the key. Earlier advice inferred causes without sufficient evidence; do not repeat it.
- Do not ask the user for decisions already authorized or infer that missing live API validation passes. Keep live AI/customer acceptance BLOCKED/UNVERIFIED while independent development proceeds.
- Sentence-level technical meaning has priority. Correct words/numbers alone do not certify a correct engineering statement. Preserve negation, conditions, obligations, process order, entity relationships, quantities, units and product codes.
- Reference-backed terminology is contextual reference data, not model weight training. Do not label unreviewed candidate sources as official approved terms. Keep final evaluation documents separate from development examples.
- Use existing /workspace/urs-ai-report. Do not create worktrees unless requested. Do not modify /workspace/guion-vivo.
- Never expose secrets, process environments or credential files. Exclude .env, .runtime, .venv and credentials from packages. .env.example must remain blank.
- Tests use temporary databases and explicit fixture-only AI providers. Never qualify a real model or approve a real customer document using synthetic results.
- Run affected stage tests first; only after they pass run dependent stages. Final check is python scripts/validate.py; inspect every exit code, test counts and current source fingerprints. Keep false/skipped/unrun/live-vs-fixture outcomes distinct.
- Update docs/checklist.md, docs/HANDOFF.md, docs/validation-report.md and the safe source archive when a milestone completes. Give concise progress and final evidence; do not claim every PDF or 99% accuracy without real evaluation.

- Keep docs/PROGRESS.md as the readable user-facing checklist (completed/pending/API-deferred tables), with docs/checklist.md as detail. Present a compact status table in milestone replies. The app checklist must reflect server results, never user-toggled completion or an invented accuracy percentage.

- Before new implementation, review the whole checklist and current evidence hashes, and report the complete/pending/API-deferred overview to the user first. Backup files contain private customer data/authentication hashes: keep them operator-only and exclude SQLite databases/journals from source archives even if outside .runtime.

- UI delivery: provide screenshots directly in the conversation, not only local file links. Verify image files can be decoded. Distinguish local image rendering from confirmed visibility in the user client; do not mark client delivery PASS without evidence.
