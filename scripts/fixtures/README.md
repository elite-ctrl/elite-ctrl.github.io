# Call the Ledger fixtures

- `sample-en.docx` / `sample-tc.docx` — minimal Word packs for browser smoke tests on [figure-checker.html](../../figure-checker.html). Open the page locally, upload one file per pane, and confirm paragraph counts and figure pairing (two matched figures: amount and stock code).
- Engine regression strings live in [figure-check-fixture.mjs](../figure-check-fixture.mjs). PDF-only CLI: [run-figure-check.mjs](../run-figure-check.mjs).

# Call the Gaps fixtures

- `gaps-source.docx` / `gaps-other.docx` — paired Word packs with a clear insert, a moved paragraph, and unchanged blocks (upload to **Precedent** and **Newer one** on the tool page). Regenerate with `node scripts/create-gaps-fixtures.mjs`. Smoke the diff engine with `node scripts/run-call-the-gaps.mjs`, then open [call-the-gaps.html](../../call-the-gaps.html) and upload both files.
