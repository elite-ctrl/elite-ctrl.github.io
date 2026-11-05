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
    r.missing.length + r.extra.length + r.scaleIssues.length + r.countDiffs.length +
    (r.valueIssues ? r.valueIssues.length : 0);
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

assertNoIssues(
  "stock code zero pad EN bracket vs TC bare",
  "The stock code will be [01337].",
  "H股的股份代號為1337。"
);

const yearEn = "Revenue was HK$28.10 million in 2025.";
const yearTc = "2025年收入為港幣28.10百萬元。";
assertNoIssues("bare EN calendar year vs TC 2025年", yearEn, yearTc);

const scaleEn = "HK$85 million total.";
const scaleTc = "合共港幣85.0億元。";
const sr = compare(scaleEn, scaleTc);
if (sr.scaleIssues.length !== 1) {
  console.error("FAIL: scale pairing", sr.scaleIssues.length);
  process.exitCode = 1;
} else {
  console.log("ok: scale verify pairing");
}

const scaleFalseEn = "HK$85 million brokerage.";
const scaleFalseTc = "經紀佣金85%。";
const sfr = compare(scaleFalseEn, scaleFalseTc);
if (sfr.scaleIssues.length !== 0) {
  console.error("FAIL: scale must not pair amount with percent", sfr.scaleIssues.length);
  process.exitCode = 1;
} else if (sfr.missing.length + sfr.extra.length === 0) {
  console.error("FAIL: amount vs percent should surface issues");
  process.exitCode = 1;
} else {
  console.log("ok: scale verify skips percent digit collision");
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

const nearEn =
  "Ledger Source (EN)\n" +
  "Annual Results Summary — Stock Code: 09988\n" +
  "For the year ended 31 December 2025\n" +
  "Revenue for the year amounted to HKD 1,234.5 million,\n" +
  "representing an increase of 12.5% as compared with the prior year.\n" +
  "Profit attributable to shareholders was HKD 456.0 million.\n" +
  "Total assets stood at HKD 8,900.0 million as at 31 December 2025.\n" +
  "Board of Directors\n" +
  "Hong Kong, 31 December 2025";
const nearTc =
  "Ledger Translation (TC)\n" +
  "全年業績摘要 — 股份代號：09988\n" +
  "截至二零二五年十二月三十一日止年度\n" +
  "本年度收益為港幣1,235.5百萬元，\n" +
  "較去年增加12.5%。\n" +
  "股東應佔溢利為港幣456.0百萬元。\n" +
  "於二零二五年十二月三十一日，總資產為港幣8,900.0百萬元。\n" +
  "董事會\n" +
  "香港，二零二五年十二月三十一日";
const nr = compare(nearEn, nearTc);
const nearPairs = nr.valueIssues || [];
if (nearPairs.length !== 1) {
  console.error("FAIL: near-match should be one value mismatch", {
    valueIssues: nearPairs.length,
    missing: nr.missing.map((e) => e.key),
    extra: nr.extra.map((e) => e.key),
    matched: nr.matched.length,
  });
  process.exitCode = 1;
} else if (nr.missing.length || nr.extra.length) {
  console.error("FAIL: near-match must not stay as missing/extra", {
    missing: nr.missing.map((e) => e.key),
    extra: nr.extra.map((e) => e.key),
  });
  process.exitCode = 1;
} else if (nr.matched.length !== 5) {
  console.error("FAIL: official ledger pack should match 5 other figures", nr.matched.map((e) => e.key));
  process.exitCode = 1;
} else {
  const srcHit = nearPairs[0].src.src[0].text;
  const tgtHit = nearPairs[0].tgt.tgt[0].text;
  if (!/1,234\.5/.test(srcHit) || !/1,235\.5/.test(tgtHit)) {
    console.error("FAIL: value mismatch pair texts", srcHit, tgtHit);
    process.exitCode = 1;
  } else {
    console.log("ok: near-match amount is a paired value mismatch");
  }
}

const orphanEn = "Only this HKD 1,234.5 million appears on the source.";
const orphanTc = "翻譯只有股份代號09988。";
const orr = compare(orphanEn, orphanTc);
if (!orr.missing.some((e) => /1234\.5|1\.2345e\+9/i.test(e.key) || /1234500000/.test(e.key))) {
  console.error("FAIL: true missing amount should stay missing", orr.missing.map((e) => e.key));
  process.exitCode = 1;
} else if ((orr.valueIssues || []).length) {
  console.error("FAIL: orphan amount must not become a value mismatch");
  process.exitCode = 1;
} else {
  console.log("ok: true missing amount stays missing");
}

if (process.exitCode) {
  process.exit(process.exitCode);
}
console.log("All fixtures passed.");
