#!/usr/bin/env node
"use strict";

var fs = require("fs");
var path = require("path");
var vm = require("vm");

var htmlPath = path.join(__dirname, "..", "figure-checker.html");
var html = fs.readFileSync(htmlPath, "utf8");
var start = html.indexOf("/*ENGINE-START*/");
var end = html.indexOf("/*ENGINE-END*/");
if (start < 0 || end < 0) {
  console.error("Engine markers missing in figure-checker.html");
  process.exit(1);
}
var code = html.slice(start, end + "/*ENGINE-END*/".length);
var ctx = {};
vm.createContext(ctx);
vm.runInContext(
  code +
    "\nthis.compare = compare;" +
    "\nthis.extract = extract;" +
    "\nthis.displayedDp = displayedDp;" +
    "\nthis.canRoundItems = canRoundItems;" +
    "\nthis.detectPolarity = detectPolarity;" +
    "\nthis.normalize = normalize;" +
    "\nthis.preprocessText = preprocessText;",
  ctx
);
var compare = ctx.compare;

var passed = 0;
var failed = 0;

function counts(r) {
  return {
    matched: r.matched.length,
    missing: r.missing.length,
    extra: r.extra.length,
    scale: (r.scaleIssues || []).length,
    value: (r.valueIssues || []).length,
    rounding: (r.roundingIssues || []).length,
    direction: (r.directionIssues || []).length,
    count: (r.countDiffs || []).length
  };
}

function fmt(c) {
  return Object.keys(c).map(function (k) { return k + "=" + c[k]; }).join(" ");
}

function check(name, cond, detail) {
  if (cond) {
    console.log("  PASS  " + name);
    passed += 1;
  } else {
    console.log("  FAIL  " + name + (detail ? " — " + detail : ""));
    failed += 1;
  }
}

function expectZeroIssuesExcept(r, allowed) {
  var c = counts(r);
  allowed = allowed || {};
  var surprises = [];
  Object.keys(c).forEach(function (k) {
    var want = allowed[k] || 0;
    if (c[k] !== want) surprises.push(k + " got " + c[k] + " want " + want);
  });
  return surprises;
}

console.log("Call the Ledger — direction and rounding self-test");
console.log("");

console.log("1. Live regressions stay green");
(function () {
  var r = compare("The consideration is HK$1,234.5 million.", "代價為港幣1,234.5百萬元。");
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("1a. HK$1,234.5 million = 港幣1,234.5百萬元 matched", s.length === 0 && r.matched.length === 1, fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();
(function () {
  var r = compare("The consideration is HK$1,234.5 million.", "代價為12.345億元。");
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("1b. HK$1,234.5 million = 12.345億元 matched", s.length === 0 && r.matched.length === 1, fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();
(function () {
  var r = compare("Dated 30 June 2025.", "日期為二零二五年六月三十日。");
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("1c. 30 June 2025 = 二零二五年六月三十日 matched", s.length === 0 && r.matched.length === 1, fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();
(function () {
  var r = compare("The margin was 12%.", "利潤率為百分之十二。");
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("1d. 12% = 百分之十二 matched", s.length === 0 && r.matched.length === 1, fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();
(function () {
  var r = compare("The fee is HK$12 million.", "費用為港幣12元。");
  check("1e. scale issue still fires for same digits, different scale",
    r.scaleIssues.length === 1 && r.roundingIssues.length === 0 && r.valueIssues.length === 0,
    fmt(counts(r)));
})();
(function () {
  var r = compare("The balance is HK$100.", "結餘為港幣101.5元。");
  var rel = r.valueIssues[0] ? Math.abs(100 - 101.5) / 101.5 : null;
  check("1f. non-rounding 2% value mismatch (HK$100 vs HK$101.5, relDiff " + (rel == null ? "n/a" : rel.toFixed(4)) + ") is value, not rounding",
    r.valueIssues.length === 1 && r.roundingIssues.length === 0 && r.directionIssues.length === 0,
    fmt(counts(r)));
})();
(function () {
  var r = compare("Revenue was 5%.", "收益為6%。");
  check("1g. missing/extra still fire (5% vs 6%)",
    r.missing.length === 1 && r.extra.length === 1 && r.roundingIssues.length === 0 && r.valueIssues.length === 0 && r.matched.length === 0,
    fmt(counts(r)));
})();
(function () {
  var r = compare("The margin is 25%.", "利潤率為25.0%。");
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("1h. 25% and 25.0% stay matched", s.length === 0 && r.matched.length === 1, fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();

console.log("");
console.log("2. Direction conflict");
(function () {
  var r = compare("Revenue increased 5% year on year.", "收益按年減少5%。");
  var ok = r.directionIssues.length === 1 && r.matched.length === 0 && r.roundingIssues.length === 0 && r.valueIssues.length === 0;
  var cues = r.directionIssues[0] ? (r.directionIssues[0].srcCue + " vs " + r.directionIssues[0].tgtCue) : "none";
  check("2. “Revenue increased 5% year on year.” vs 「收益按年減少5%。」 → one direction issue, not a silent match",
    ok, fmt(counts(r)) + " cues=" + cues);
})();

console.log("");
console.log("3. Direction agrees");
(function () {
  var r = compare("Revenue increased 5%.", "收益增加5%。");
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("3. “Revenue increased 5%.” vs 「收益增加5%。」 → matched, no direction flag",
    s.length === 0 && r.matched.length === 1 && r.directionIssues.length === 0,
    fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();

console.log("");
console.log("4. One-sided cue");
(function () {
  var r = compare("Revenue increased 5%.", "收益為5%。");
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("4. “Revenue increased 5%.” vs 「收益為5%。」 → no direction flag",
    s.length === 0 && r.directionIssues.length === 0 && r.matched.length === 1,
    fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();

console.log("");
console.log("5. Negation");
(function () {
  var r = compare("Revenue did not increase 5%.", "收益並無增加5%。");
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("5. “Revenue did not increase 5%.” vs 「收益並無增加5%。」 → no direction flag",
    s.length === 0 && r.directionIssues.length === 0 && r.matched.length === 1,
    fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();

console.log("");
console.log("6. “Up to” is not up");
(function () {
  var r = compare("Growth is capped at up to 5%.", "升幅最多5%。");
  // "升幅" is an up cue on the TC side; "up to" / "capped at" / 最多 must not create a conflict.
  // If 升幅 is present, EN must stay none, so one-sided → no flag. Figures still match.
  var s = expectZeroIssuesExcept(r, { matched: 1 });
  check("6. “up to 5%” vs 「最多5%」 → no direction flag",
    r.directionIssues.length === 0 && r.matched.length === 1,
    fmt(counts(r)) + (s.length ? " | " + s.join("; ") : ""));
})();
(function () {
  var r = compare("Growth of up to 5%.", "最多5%。");
  check("6b. “up to 5%” vs 「最多5%」 with no other verb → no direction flag",
    r.directionIssues.length === 0 && r.matched.length === 1,
    fmt(counts(r)));
})();

console.log("");
console.log("7. Rounding with agreeing direction");
(function () {
  var r = compare("Profit margin increased 25.04%.", "利潤率增加25.0%。");
  check("7. 25.04% vs 25.0% with increased / 增加 → rounding, not value, not silent match",
    r.roundingIssues.length === 1 && r.valueIssues.length === 0 && r.matched.length === 0 && r.directionIssues.length === 0 && r.missing.length === 0 && r.extra.length === 0,
    fmt(counts(r)));
})();
(function () {
  var r = compare("The figure was 12.345.", "該數字為12.35。");
  check("7b. 12.345 vs 12.35 is rounding",
    r.roundingIssues.length === 1 && r.valueIssues.length === 0,
    fmt(counts(r)));
})();
(function () {
  var r = compare("The figure was 1,234.56.", "該數字為1,235。");
  check("7c. 1,234.56 vs 1,235 is rounding",
    r.roundingIssues.length === 1 && r.valueIssues.length === 0,
    fmt(counts(r)));
})();
(function () {
  var r = compare("The rate was 1.4%.", "比率為1%。");
  check("7d. 1.4% vs 1% (relDiff > 2%) still rounding, not missing/extra",
    r.roundingIssues.length === 1 && r.missing.length === 0 && r.extra.length === 0 && r.valueIssues.length === 0,
    fmt(counts(r)));
})();

console.log("");
console.log("8. Direction and rounding together");
(function () {
  var r = compare("The margin increased 25.04%.", "利潤率減少25.0%。");
  var p = r.directionIssues[0] || {};
  var ok = r.directionIssues.length === 1 && r.roundingIssues.length === 1 && p.alsoRounding === true &&
    r.valueIssues.length === 0 && r.matched.length === 0;
  check("8. “increased 25.04%” vs 「減少25.0%」 → direction + rounding on that pair",
    ok, fmt(counts(r)) + " alsoRounding=" + p.alsoRounding + " cues=" + (p.srcCue || "") + " vs " + (p.tgtCue || ""));
})();

console.log("");
console.log("9. Same decimal places is not rounding");
(function () {
  var r = compare("The margin increased 25.04%.", "利潤率增加25.05%。");
  check("9. 25.04 vs 25.05 (agreeing direction) → NOT rounding; value mismatch if within 2%",
    r.roundingIssues.length === 0 && r.valueIssues.length === 1 && r.directionIssues.length === 0,
    fmt(counts(r)));
})();

console.log("");
console.log("10. 獲利回吐 is not a down cue");
(function () {
  var r = compare("Revenue increased 5%.", "期間獲利回吐5%。");
  check("10. 獲利回吐 near a number is not a down cue by itself (no direction flag against increased)",
    r.directionIssues.length === 0 && r.matched.length === 1,
    fmt(counts(r)));
})();

console.log("");
console.log("Results: " + passed + " passed, " + failed + " failed");
if (failed) {
  process.exit(1);
}
console.log("ALL TESTS PASSED");
