#!/usr/bin/env node
/**
 * Offline runner for Call the Ledger engine (embedded in figure-checker.html).
 * Usage: node scripts/run-figure-check.mjs <source.pdf> <translation.pdf>
 *
 * Word (.docx) packs are checked in the browser on figure-checker.html (Mammoth.js);
 * this script remains PDF-only for offline engine regression.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";
import { createRequire } from "module";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
const require = createRequire(import.meta.url);

const html = fs.readFileSync(path.join(root, "figure-checker.html"), "utf8");
const m = html.match(/\/\*ENGINE-START\*\/([\s\S]*?)\/\*ENGINE-END\*\//);
if (!m) {
  console.error("ENGINE block not found");
  process.exit(1);
}
const engine = m[1];
const fn = new Function(engine + "\nreturn { extract, compare, keyOf, buildMatchers, normalize };");
const { extract, compare } = fn();

const pdfjsPath = path.join(root, "assets/pdfjs/pdf.min.js");
const pdfjsLib = require(pdfjsPath);
pdfjsLib.GlobalWorkerOptions.workerSrc = path.join(root, "assets/pdfjs/pdf.worker.min.js");

function isCjkChar(ch) {
  return /[\u3400-\u9FFF\uF900-\uFAFF]/.test(ch);
}
function itemsToText(items) {
  let out = "";
  let lastY = null;
  let lastEnd = null;
  let lastChar = "";
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const str = item.str || "";
    if (!str) continue;
    const tr = item.transform || [0, 0, 0, 0, 0, 0];
    const x = tr[4];
    const y = tr[5];
    const size = Math.abs(tr[3]) || item.height || 10;
    if (lastY !== null && Math.abs(y - lastY) > size * 0.8) {
      out += "\n";
      lastEnd = null;
      lastChar = "\n";
    }
    if (lastEnd !== null && out && !/\s$/.test(out)) {
      const gap = x - lastEnd;
      const prevCjk = isCjkChar(lastChar);
      const nextCjk = isCjkChar(str.charAt(0));
      if (!prevCjk && !nextCjk && gap > size * 0.25) out += " ";
    }
    out += str;
    lastY = y;
    lastEnd = x + (item.width || 0);
    lastChar = str.charAt(str.length - 1);
    if (item.hasEOL) {
      out += "\n";
      lastY = null;
      lastEnd = null;
      lastChar = "\n";
    }
  }
  return out.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n");
}

async function extractPdfText(filePath) {
  const buf = fs.readFileSync(filePath);
  const task = pdfjsLib.getDocument({
    data: new Uint8Array(buf),
    cMapUrl: path.join(root, "assets/pdfjs/cmaps/") + path.sep,
    cMapPacked: true,
    standardFontDataUrl: path.join(root, "assets/pdfjs/standard_fonts/") + path.sep,
    disableFontFace: true,
    isEvalSupported: false,
  });
  const pdf = await task.promise;
  const chunks = [];
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    const content = await page.getTextContent();
    chunks.push(itemsToText(content.items));
  }
  await pdf.destroy();
  return chunks.join("\n\n");
}

const srcPath = process.argv[2];
const tgtPath = process.argv[3];
if (!srcPath || !tgtPath) {
  console.error("Usage: node scripts/run-figure-check.mjs <source.pdf> <translation.pdf>");
  process.exit(1);
}

const srcText = await extractPdfText(srcPath);
const tgtText = await extractPdfText(tgtPath);
const r = compare(srcText, tgtText);

const valueIssues = r.valueIssues || [];
const issueCount =
  r.missing.length + r.extra.length + r.scaleIssues.length + valueIssues.length + r.countDiffs.length;
console.log("Source figures:", extract(srcText).length);
console.log("Translation figures:", extract(tgtText).length);
console.log("Matched:", r.matched.length);
console.log("Missing:", r.missing.length);
console.log("Extra:", r.extra.length);
console.log("Scale verify:", r.scaleIssues.length);
console.log("Value mismatch:", valueIssues.length);
console.log("Count diffs:", r.countDiffs.length);
console.log("Issue rows:", issueCount);
console.log("\n--- MISSING ---");
for (const e of r.missing) {
  const it = e.src[0];
  console.log(e.key, "|", it.text, "|", (it.before + it.text + it.after).replace(/\n/g, " "));
}
console.log("\n--- EXTRA ---");
for (const e of r.extra) {
  const it = e.tgt[0];
  console.log(e.key, "|", it.text, "|", (it.before + it.text + it.after).replace(/\n/g, " "));
}
console.log("\n--- SCALE ---");
for (const p of r.scaleIssues) {
  console.log(p.src.src[0].text, "vs", p.tgt.tgt[0].text);
}
console.log("\n--- VALUE MISMATCH ---");
for (const p of valueIssues) {
  console.log(p.src.src[0].text, "vs", p.tgt.tgt[0].text);
}
console.log("\n--- COUNT DIFF ---");
for (const e of r.countDiffs) {
  console.log(e.key, e.src.length, "vs", e.tgt.length, sideTexts(e));
}
function sideTexts(e) {
  return e.src.map((it) => it.text).join(" · ");
}

if (process.env.FIGURE_CHECK_STRICT === "1" && issueCount > 0) {
  process.exit(1);
}
