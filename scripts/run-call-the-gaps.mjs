#!/usr/bin/env node
/**
 * Offline smoke for Call the Gaps diff engine.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";
import { createRequire } from "module";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
const require = createRequire(import.meta.url);

const diffPath = path.join(root, "assets/call-the-gaps-diff.js");
const code = fs.readFileSync(diffPath, "utf8");
const vm = await import("vm");
const context = { globalThis: {}, window: {} };
context.window = context.globalThis;
vm.runInNewContext(code, context);
const { compareTexts } = context.globalThis.CallTheGapsDiff;

const src = [
  "Revenue increased by ten per cent in the first half.",
  "The board declared an interim dividend.",
  "Operating profit was stable year on year.",
  "Net assets rose to five billion dollars."
].join("\n\n");

const tgt = [
  "Revenue increased by ten per cent in the first half.",
  "Operating profit was stable year on year.",
  "The Group opened a new office in Singapore.",
  "Net assets rose to five billion dollars.",
  "The board declared an interim dividend."
].join("\n\n");

const result = compareTexts(src, tgt);
console.log("Summary:", result.summary);
console.log("Changes:");
result.changes.forEach(function (c) {
  console.log(" -", c.type + ":", c.snippet);
});

const types = new Set(result.changes.map((c) => c.type));
const ok =
  result.summary.insert >= 1 &&
  types.has("insert") &&
  (types.has("move") || result.summary.move >= 1);
if (!ok) {
  console.error("Fixture check failed: expected insert + move");
  process.exit(1);
}
console.log("Fixture check passed.");
