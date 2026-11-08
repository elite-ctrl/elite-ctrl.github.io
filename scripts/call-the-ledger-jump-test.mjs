#!/usr/bin/env node
/**
 * Headless check: summary type chips / bottom error chips / pair-rows
 * jump to the matching issue row on Call the Ledger.
 *
 *   python3 -m http.server 8765 --bind 127.0.0.1
 *   npm install --no-save puppeteer-core
 *   node scripts/call-the-ledger-jump-test.mjs
 */
import puppeteer from "puppeteer-core";

const BASE = process.env.LEDGER_BASE || "http://127.0.0.1:8765";
const CHROME = process.env.CHROME_PATH || "/usr/local/bin/google-chrome";

function filler(n, tag) {
  const paras = [];
  for (let i = 0; i < n; i++) {
    paras.push(
      "Filler " + tag + " " + i + ". The Company continues to disclose operating metrics in both languages."
    );
  }
  return paras.join("\n\n");
}

const src = [
  filler(2, "top"),
  "Revenue for the year amounted to HKD 1,234.5 million.",
  "Scale check HK$85 million total.",
  "Discount 5%. Rebate 5%.",
  "Missing only in source HK$77.7 million.",
  "Another missing HK$88.8 million.",
  "Third missing HK$99.9 million.",
  "Fourth missing HK$66.6 million.",
  "Fifth missing HK$55.5 million.",
  "Sixth missing HK$99.1 million.",
  "Stock code: 09988"
].join("\n\n");

const tgt = [
  filler(2, "top"),
  "本年度收益為港幣1,235.5百萬元。",
  "合共港幣85.0億元。",
  "折扣5%。",
  "翻譯獨有港幣22.2百萬元。",
  "另一獨有港幣33.3百萬元。",
  "股份代號：09988"
].join("\n\n");

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
  await page.goto(BASE + "/figure-checker.html", { waitUntil: "networkidle0", timeout: 30000 });
  await page.waitForFunction(() => window.FigureChecker && window.FigureChecker.setTexts);

  await page.evaluate(
    (a, b) => {
      window.FigureChecker.setTexts(a, b);
    },
    src,
    tgt
  );

  await page.waitForSelector(".error-chip");
  const inventory = await page.evaluate(() => {
    const chips = Array.from(document.querySelectorAll(".error-chip"));
    const rows = Array.from(document.querySelectorAll(".pair-row[data-issue-id]"));
    const types = chips.map((el) => el.getAttribute("data-issue-type"));
    return {
      chipCount: chips.length,
      rowCount: rows.length,
      types,
      typeChips: Array.from(document.querySelectorAll("[data-jump-type]")).map((el) =>
        el.getAttribute("data-jump-type")
      ),
      matchedChipIsButton: !!document.querySelector(".summary .chip.ok[data-jump-type]")
    };
  });
  assert(inventory.chipCount >= 8, "expected several error chips, got " + inventory.chipCount);
  assert(inventory.rowCount === inventory.chipCount, "each issue chip should map to a pair-row");
  ["miss", "extra", "scale", "value", "count"].forEach((t) => {
    assert(inventory.types.includes(t), "missing " + t + " chip");
    assert(inventory.typeChips.includes(t), "missing summary type chip for " + t);
  });
  assert(!inventory.matchedChipIsButton, "matched summary chip should stay non-jumping");

  async function clickSelector(sel) {
    await page.click(sel);
    await page.waitForFunction(
      (s) => {
        const el = document.querySelector(s);
        if (!el) return false;
        const id = el.getAttribute("data-issue-id") || el.getAttribute("data-jump-type");
        if (!id) return false;
        if (el.hasAttribute("data-jump-type")) {
          return !!document.querySelector(".pair-row[data-issue-id].is-active");
        }
        return !!document.querySelector('.pair-row[data-issue-id="' + id + '"].is-active');
      },
      { timeout: 4000 },
      sel
    );
    return page.evaluate((s) => {
      const el = document.querySelector(s);
      const id = el.getAttribute("data-issue-id");
      const active = document.querySelector(".pair-row.is-active");
      const chip = id
        ? document.querySelector('.error-chip[data-issue-id="' + id + '"]')
        : document.querySelector(".error-chip.is-current");
      function box(node) {
        const r = node.getBoundingClientRect();
        return { y: r.top, height: r.height, bottom: r.bottom };
      }
      const rowBox = active ? box(active) : null;
      const mid = rowBox ? rowBox.y + rowBox.height / 2 : null;
      return {
        id: active && active.getAttribute("data-issue-id"),
        type: active && active.getAttribute("data-issue-type"),
        chipCurrent: !!(chip && chip.classList.contains("is-current")),
        scrollY: window.scrollY,
        rowVisible: mid != null && mid >= 0 && mid <= window.innerHeight,
        pageOverflow: document.documentElement.scrollHeight - window.innerHeight
      };
    }, sel);
  }

  const scale = await clickSelector('[data-jump-type="scale"]');
  assert(scale.type === "scale", "scale summary chip should land on a scale row, got " + JSON.stringify(scale));
  assert(scale.rowVisible, "scale row should be in the viewport");
  assert(scale.chipCurrent, "matching bottom chip should be current");

  const miss1 = await clickSelector('[data-jump-type="miss"]');
  assert(miss1.type === "miss", "miss summary chip should land on a missing row");
  assert(miss1.rowVisible, "first miss row should be in the viewport");
  const miss1Id = miss1.id;

  const miss2 = await clickSelector('[data-jump-type="miss"]');
  assert(miss2.type === "miss", "second miss click should stay on missing rows");
  assert(miss2.id !== miss1Id, "type chip should cycle to the next missing issue");
  assert(miss2.rowVisible, "cycled miss row should be in the viewport");

  const extraChip = await clickSelector('.error-chip[data-issue-type="extra"]');
  assert(extraChip.type === "extra", "extra bottom chip should land on an extra row");
  assert(extraChip.rowVisible, "extra row should be in the viewport");

  const lastChipSel = await page.evaluate(() => {
    const chips = document.querySelectorAll(".error-chip");
    const last = chips[chips.length - 1];
    return '.error-chip[data-issue-id="' + last.getAttribute("data-issue-id") + '"]';
  });
  const last = await clickSelector(lastChipSel);
  assert(last.pageOverflow > 80, "results should overflow so jump can scroll, overflow=" + last.pageOverflow);
  assert(last.scrollY > 20, "last-issue jump should scroll the page, got " + last.scrollY);
  assert(last.rowVisible, "last issue row should be in the viewport after jump");

  const rowClick = await page.evaluate(async () => {
    const row = document.querySelector('.pair-row[data-issue-type="value"]');
    row.click();
    await new Promise((r) => setTimeout(r, 40));
    return {
      activeId: document.querySelector(".pair-row.is-active") &&
        document.querySelector(".pair-row.is-active").getAttribute("data-issue-id"),
      rowId: row.getAttribute("data-issue-id"),
      chipCurrent: !!document.querySelector(
        '.error-chip[data-issue-id="' + row.getAttribute("data-issue-id") + '"].is-current'
      )
    };
  });
  assert(rowClick.activeId === rowClick.rowId, "clicking a pair-row should highlight that row");
  assert(rowClick.chipCurrent, "pair-row click should mark the matching bottom chip");

  await page.reload({ waitUntil: "networkidle0" });
  await page.waitForFunction(() => window.FigureChecker);
  const srcInput = await page.$("#srcFile");
  const tgtInput = await page.$("#tgtFile");
  await srcInput.uploadFile("scripts/fixtures/spellout-en.docx");
  await tgtInput.uploadFile("scripts/fixtures/spellout-tc.docx");
  await page.waitForSelector(".error-chip", { timeout: 15000 });
  await page.click(".error-chip");
  await page.waitForSelector(".pair-row.is-active", { timeout: 4000 });
  const wordJump = await page.evaluate(() => {
    const chip = document.querySelector(".error-chip.is-current");
    const row = document.querySelector(".pair-row.is-active");
    return {
      chipType: chip && chip.getAttribute("data-issue-type"),
      rowType: row && row.getAttribute("data-issue-type"),
      sameId:
        chip &&
        row &&
        chip.getAttribute("data-issue-id") === row.getAttribute("data-issue-id")
    };
  });
  assert(wordJump.chipType === "value", "Word fixtures: expected a value-mismatch chip, got " + JSON.stringify(wordJump));
  assert(wordJump.sameId, "Word fixtures: chip click should highlight the matching pair-row");

  console.log("PASS", { inventory, scale, miss1, miss2, extraChip, last, rowClick, wordJump });
} finally {
  await browser.close();
}
