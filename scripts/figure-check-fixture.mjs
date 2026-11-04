#!/usr/bin/env node
/**
 * Regression fixtures for Call the Ledger (figure-checker.html engine).
 * Run: node scripts/figure-check-fixture.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "figure-checker.html"), "utf8");
const m = html.match(/\/\*ENGINE-START\*\/([\s\S]*?)\/\*ENGINE-END\*\//);
if (!m) {
  console.error("ENGINE block not found");
  process.exit(1);
}
const fn = new Function(m[1] + "\nreturn { compare, extract };");
const { compare, extract } = fn();

function assertNoIssues(name, en, tc) {
  const r = compare(en, tc);
  const issues =
    r.missing.length + r.extra.length + r.scaleIssues.length + r.countDiffs.length;
  if (issues !== 0) {
    console.error("FAIL:", name, {
      missing: r.missing.map((e) => e.key),
      extra: r.extra.map((e) => e.key),
      scale: r.scaleIssues.length,
      countDiffs: r.countDiffs.map((e) => e.key),
    });
    process.exitCode = 1;
    return;
  }
  console.log("ok:", name);
}

const proofEn =
  "File: e_27660_AD(5) Project Thundering Horses 1st Proof 210(W)x280(H) (820) 2nd November 2026\n" +
  "23 : 17 BL:(1-9)/(9) P.1 (L1) (E>C)\nBody HK$28.10 million of offer.";
const proofTc =
  "File: c_27660_AD(5) Project Thundering Horses 1st Proof 210(W)x280(H) (710) 3rd November 2026\n" +
  "13 : 18 BL:(1-13)/(13) P.1 (L1) (E>C)\nBody 港幣28.10百萬元。";
assertNoIssues("proof headers stripped", proofEn, proofTc);
// Different folio / page proof lines (11 vs 13 pages in live packs) — whole-document compare, not page-gated.

const datesEn =
  "Listing on [Friday, December 11], 2026 and [Wednesday, December 16], 2026.\n" +
  "Prospectus dated [December 3], 2026.";
const datesTc =
  "上市日期2026年12月11日（星期五）及2026年12月16日（星期三）。\n" +
  "招股章程日期2026年12月3日。";
assertNoIssues("bracket EN dates vs TC dates", datesEn, datesTc);

const spacedTc = "最高發售價每股H股2 8 . 1 0港元，另加1 . 0 %經紀佣金。";
const spacedEn = "Maximum Offer Price HK$28.10 per H Share, plus 1.0% brokerage.";
assertNoIssues("spaced TC price and percent", spacedEn, spacedTc);

const codeEn = "The stock code of the H Shares will be [01337].";
const codeTc = "H股的股份代號將為[01337]。";
assertNoIssues("stock code placeholder", codeEn, codeTc);

const scaleEn = "HK$85 million total.";
const scaleTc = "合共港幣85.0億元。";
const sr = compare(scaleEn, scaleTc);
if (sr.scaleIssues.length !== 1) {
  console.error("FAIL: scale pairing", sr.scaleIssues.length);
  process.exitCode = 1;
} else {
  console.log("ok: scale verify pairing");
}

const bracketAmtEn = "then up to [1,029,000] Offer Shares may be reallocated.";
const bracketAmtTc = "– 5 –最多可將[1,029,000]股發售股份重新分配。";
assertNoIssues("bracket comma amounts near folio", bracketAmtEn, bracketAmtTc);

const clockEn =
  "Commence at 9 : 00 a.m. on [Thursday, December 3], 2026 and end at 12 : 00 noon on [Tuesday, December 8, 2026].";
const clockTc =
  "於2026年12月3日（星期四）上午九時正開始，於2026年12月8日（星期二）中午十二時正結束。";
assertNoIssues("clock times vs Chinese times", clockEn, clockTc);

const amEn = "The offer opens at 9 a.m. on the Offer Date.";
const amTc = "發售於發售日期上午九時開始。";
assertNoIssues("hour without colon before a.m.", amEn, amTc);

const pctCountEn = "Discount 5%. Rebate 5%.";
const pctCountTc = "折扣5%。";
const pcr = compare(pctCountEn, pctCountTc);
if (pcr.countDiffs.length !== 1 || pcr.countDiffs[0].key !== "pct|5") {
  console.error("FAIL: percent count diff", pcr.countDiffs);
  process.exitCode = 1;
} else {
  console.log("ok: percent count diff surfaced");
}

if (process.exitCode) {
  process.exit(process.exitCode);
}
console.log("All fixtures passed.");
