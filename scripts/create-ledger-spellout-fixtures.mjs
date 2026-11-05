#!/usr/bin/env node
/** Build Word packs that plant spell-out ↔ digit match and value-mismatch rows. */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(__dirname, "fixtures");
const tmp = path.join(outDir, ".ledger-spellout-docx-build");

function para(text) {
  return (
    "<w:p><w:r><w:t xml:space=\"preserve\">" +
    text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") +
    "</w:t></w:r></w:p>"
  );
}

function buildDocx(paragraphs, filename) {
  const body = paragraphs.map(para).join("");
  const documentXml =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
    "<w:body>" +
    body +
    "</w:body></w:document>";
  const contentTypes =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
    "</Types>";
  const rels =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
    "</Relationships>";
  const workDir = path.join(tmp, filename.replace(".docx", ""));
  fs.rmSync(workDir, { recursive: true, force: true });
  fs.mkdirSync(path.join(workDir, "word"), { recursive: true });
  fs.mkdirSync(path.join(workDir, "_rels"), { recursive: true });
  fs.writeFileSync(path.join(workDir, "[Content_Types].xml"), contentTypes);
  fs.writeFileSync(path.join(workDir, "_rels", ".rels"), rels);
  fs.writeFileSync(path.join(workDir, "word", "document.xml"), documentXml);
  const outPath = path.join(outDir, filename);
  fs.rmSync(outPath, { force: true });
  execSync(`cd "${workDir}" && zip -qr "${outPath}" .`, { stdio: "inherit" });
}

const en = [
  "Call the Ledger spell-out pack (EN)",
  "The margin rose twelve per cent year on year.",
  "Profit attributable to shareholders was one hundred and twenty million.",
  "Consideration was HK$1.2 million.",
  "Stock code: 09988"
];
const tc = [
  "Call the Ledger 拼寫數字包（TC）",
  "利潤率按年上升百分之十二。",
  "股東應佔溢利為港幣1.21億元。",
  "代價為一百二十萬元。",
  "股份代號：09988"
];

buildDocx(en, "spellout-en.docx");
buildDocx(tc, "spellout-tc.docx");
fs.rmSync(tmp, { recursive: true, force: true });
console.log("Wrote spellout-en.docx and spellout-tc.docx");
