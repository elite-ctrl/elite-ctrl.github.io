# Call the Ledger fixtures

- `sample-en.docx` / `sample-tc.docx` — minimal Word packs for browser smoke tests on [figure-checker.html](../../figure-checker.html). Open the page locally, upload one file per pane, and confirm paragraph counts and figure pairing (two matched figures: amount and stock code).
- `spellout-en.docx` / `spellout-tc.docx` — planted finance spell-outs for the Beta lexicon slice. Expect three matched figures (twelve per cent ↔ 百分之十二, HK$1.2 million ↔ 一百二十萬, 09988) and one value mismatch (one hundred and twenty million ↔ 港幣1.21億元). Regenerate with `node scripts/create-ledger-spellout-fixtures.mjs`.
- Engine regression strings live in [figure-check-fixture.mjs](../figure-check-fixture.mjs). PDF-only CLI: [run-figure-check.mjs](../run-figure-check.mjs).

# Call the Gaps fixtures

- `gaps-source.docx` / `gaps-other.docx` — paired Word packs with a clear insert, a moved paragraph, and unchanged blocks (upload to **Precedent** and **Newer one** on the tool page). Regenerate with `node scripts/create-gaps-fixtures.mjs`. Smoke the diff engine with `node scripts/run-call-the-gaps.mjs`, then open [call-the-gaps.html](../../call-the-gaps.html) and upload both files.
