#!/usr/bin/env node
/**
 * Edge-case harness for Call the Gaps diff engine.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
const diffCode = fs.readFileSync(path.join(root, "assets/call-the-gaps-diff.js"), "utf8");
const ctx = { globalThis: {}, window: {} };
ctx.window = ctx.globalThis;
await import("vm").then((vm) => vm.runInNewContext(diffCode, ctx));
const { compareTexts, tokenize, splitParagraphs, orderSegmentsForSide } = ctx.globalThis.CallTheGapsDiff;

function assert(cond, msg) {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exitCode = 1;
    throw new Error(msg);
  }
}

function summarize(label, a, b) {
  const r = compareTexts(a, b);
  console.log(
    label,
    "→",
    JSON.stringify(r.summary),
    "changes:",
    r.changes.map((c) => c.type).join(",") || "none"
  );
  return r;
}

// Identical
{
  const t = "Alpha one.\n\nBeta two.";
  const r = summarize("identical", t, t);
  assert(r.summary.insert === 0 && r.summary.delete === 0 && r.summary.move === 0, "identical should have no typed changes");
}

// Pure delete (paragraph removed, not moved)
{
  const a = "Keep this.\n\nRemove me entirely.\n\nAnd this.";
  const b = "Keep this.\n\nAnd this.";
  const r = summarize("pure delete", a, b);
  assert(r.summary.delete >= 1 || r.changes.some((c) => c.type === "delete"), "expect delete");
}

// Pure insert
{
  const a = "Keep this.\n\nAnd this.";
  const b = "Keep this.\n\nBrand new paragraph with enough words here.\n\nAnd this.";
  const r = summarize("pure insert", a, b);
  assert(r.summary.insert >= 1, "expect insert");
}

// Multi-move (two relocated paragraphs)
{
  const a = [
    "Paragraph AAAA one two three four five six.",
    "Paragraph BBBB one two three four five six.",
    "Paragraph CCCC one two three four five six.",
  ].join("\n\n");
  const b = [
    "Paragraph CCCC one two three four five six.",
    "Paragraph AAAA one two three four five six.",
    "Paragraph BBBB one two three four five six.",
  ].join("\n\n");
  const r = summarize("multi-move", a, b);
  assert(r.summary.move >= 2, "expect at least two moves on full rotation, got " + r.summary.move);
}

// CJK-heavy
{
  const a = "本公司截至二零二五年六月三十日止六個月之收入增加。\n\n董事會宣佈派發中期股息。";
  const b = "本公司截至二零二五年六月三十日止六個月之收入增加。\n\n本集團於新加坡設立新辦事處。\n\n董事會宣佈派發中期股息。";
  const r = summarize("CJK insert", a, b);
  assert(r.summary.insert >= 1, "CJK insert");
  const cjkTokens = tokenize("收入增加");
  assert(cjkTokens.filter((t) => t.t === "cjk").length === 4, "CJK tokenize");
}

// Single-newline doc (Word-style) — exposes paragraph split weakness
{
  const a = "Line one here.\nLine two here.\nLine three here.";
  const b = "Line one here.\nLine two changed words here.\nLine three here.";
  const paras = splitParagraphs ? splitParagraphs(a) : a.split(/\n\s*\n/);
  if (!splitParagraphs) {
    // access via re-split in compare
  }
  const r = compareTexts(a, b);
  console.log(
    "single-newline word doc →",
    JSON.stringify(r.summary),
    "segments:",
    r.segments.length,
    "types:",
    r.segments.map((s) => s.type).join("|")
  );
}

// Case-only paragraph (intra path)
{
  const a = "Revenue grew strongly in the first half.\n\nCosts were flat.";
  const b = "Revenue grew strongly in the first half.\n\nCosts were FLAT.";
  const r = summarize("case tweak same paraKey?", a, b);
  const hasIntra = r.segments.some((s) => s.type === "intra");
  console.log("  has intra segment:", hasIntra);
}

// Short move below threshold
{
  const a = "One.\n\nTwo short.\n\nThree.";
  const b = "One.\n\nThree.\n\nTwo short.";
  const r = summarize("short move", a, b);
  console.log("  (short para may stay insert+delete, not move)");
}

// Desk fixture: A → B → C vs C → A → D (B deleted, D inserted, A/C swapped)
{
  const A = "Paragraph A. The Company maintains robust internal controls over financial reporting and disclosure processes.";
  const B = "Paragraph B. Management reviews all material contracts before execution and documents the approval trail.";
  const C = "Paragraph C. External auditors are appointed annually by the shareholders at the annual general meeting.";
  const D = "Paragraph D (inserted). The Company also publishes an annual ESG report covering environmental and social metrics.";
  const r = summarize("A/C swap + insert D + delete B", [A, B, C].join("\n\n"), [C, A, D].join("\n\n"));
  assert(r.changes.some((c) => c.type === "insert" && /Paragraph D/.test(c.snippet)), "expect insert D");
  assert(r.changes.some((c) => c.type === "delete" && /Paragraph B/.test(c.snippet)), "expect delete B");
  const moves = r.changes.filter((c) => c.type === "move");
  assert(moves.length >= 2, "expect A and C both typed as moves, got " + moves.length);
  assert(moves.some((c) => /Paragraph A/.test(c.snippet)), "move should cover Paragraph A, not a first-line fragment");
  assert(moves.some((c) => /Paragraph C/.test(c.snippet)), "move should cover Paragraph C");
  const newer = orderSegmentsForSide(r.segments, "tgt").map((s) => (s.textB || "").slice(0, 12));
  assert(newer[0].indexOf("Paragraph C") === 0, "newer pane should start with C, got " + JSON.stringify(newer));
  assert(newer[1].indexOf("Paragraph A") === 0, "newer pane should show A after C, got " + JSON.stringify(newer));
  assert(newer[2].indexOf("Paragraph D") === 0, "newer pane should end with D, got " + JSON.stringify(newer));
}

// PDF soft-wrap of the same fixture (ReportLab line breaks + titles)
{
  const pdfA = [
    "Gaps Precedent",
    "Paragraph A. The Company maintains robust internal controls over financial reporting and disclosure",
    "processes.",
    "Paragraph B. Management reviews all material contracts before execution and documents the",
    "approval trail.",
    "Paragraph C. External auditors are appointed annually by the shareholders at the annual general",
    "meeting."
  ].join("\n");
  const pdfB = [
    "Gaps Newer",
    "Paragraph C. External auditors are appointed annually by the shareholders at the annual general",
    "meeting.",
    "Paragraph A. The Company maintains robust internal controls over financial reporting and disclosure",
    "processes.",
    "Paragraph D (inserted). The Company also publishes an annual ESG report covering environmental",
    "and social metrics."
  ].join("\n");
  const parasA = splitParagraphs(pdfA);
  const parasB = splitParagraphs(pdfB);
  assert(parasA.some((p) => /disclosure processes/.test(p)), "PDF wrap should join A tail 'processes.'");
  assert(parasB.some((p) => /social metrics/.test(p)), "PDF wrap should join D tail");
  assert(!parasA.includes("processes."), "soft-wrap tail must not stay a paragraph");
  const r = summarize("PDF-wrapped A/C swap", pdfA, pdfB);
  assert(r.changes.some((c) => c.type === "insert" && /Paragraph D/.test(c.snippet)), "PDF: insert D");
  assert(r.changes.some((c) => c.type === "delete" && /Paragraph B/.test(c.snippet)), "PDF: delete B");
  const moves = r.changes.filter((c) => c.type === "move");
  assert(moves.length >= 2, "PDF: expect A and C moves, got " + moves.length);
  assert(!r.changes.some((c) => /processes/.test(c.snippet) && c.type !== "move"), "PDF: no false insert/delete on wrap tail");
  const newer = orderSegmentsForSide(r.segments, "tgt")
    .map((s) => s.textB || "")
    .filter((t) => /Paragraph [ACD]/.test(t));
  assert(newer[0].indexOf("Paragraph C") === 0, "PDF newer order should be C then A then D");
  assert(newer[1].indexOf("Paragraph A") === 0, "PDF newer order A after C");
  assert(newer[2].indexOf("Paragraph D") === 0, "PDF newer order D last");
}

// Insert in the middle must not mark later paragraphs as moves
{
  const a = [
    "Revenue increased by ten per cent in the first half.",
    "The board declared an interim dividend.",
    "Operating profit was stable year on year."
  ].join("\n\n");
  const b = [
    "Revenue increased by ten per cent in the first half.",
    "The Group opened a new office in Singapore with enough words.",
    "The board declared an interim dividend.",
    "Operating profit was stable year on year."
  ].join("\n\n");
  const r = summarize("insert shifts later paras", a, b);
  assert(r.summary.insert >= 1, "expect insert");
  assert(r.summary.move === 0, "index shift from a pure insert is not a move, got " + r.summary.move);
}

console.log("\nDone. exit=", process.exitCode || 0);
