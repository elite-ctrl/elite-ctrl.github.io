#!/usr/bin/env node
/**
 * Headless check: bottom error chips / rail items jump to pane marks.
 *
 *   python3 -m http.server 8765 --bind 127.0.0.1
 *   npm install --no-save puppeteer-core
 *   node scripts/call-the-gaps-jump-test.mjs
 */
import puppeteer from "puppeteer-core";

const BASE = process.env.GAPS_BASE || "http://127.0.0.1:8765";
const CHROME = process.env.CHROME_PATH || "/usr/local/bin/google-chrome";

function filler(n, tag) {
  const paras = [];
  for (let i = 0; i < n; i++) {
    paras.push(
      "Filler " + tag + " " + i + ". The Company continues to disclose operating metrics in both languages. " +
        "This block exists so the panes overflow and jump has somewhere to scroll. ".repeat(3)
    );
  }
  return paras.join("\n\n");
}

const src =
  filler(10, "top") +
  "\n\nDELETE_UNIQUE_BLOCK The board withdrew the old indemnity clause from the pack.\n\n" +
  filler(8, "mid") +
  "\n\nMOVE_UNIQUE_BLOCK The interim dividend declaration sits here in the precedent.\n\n" +
  filler(8, "end");

const tgt =
  filler(10, "top") +
  "\n\nINSERT_UNIQUE_BLOCK The Group opened a new office in Singapore for the newer pack.\n\n" +
  filler(8, "mid") +
  "\n\n" +
  filler(8, "end") +
  "\n\nMOVE_UNIQUE_BLOCK The interim dividend declaration sits here in the precedent.";

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
  await page.goto(BASE + "/call-the-gaps.html", { waitUntil: "networkidle0", timeout: 30000 });
  await page.waitForFunction(() => window.CallTheGaps && window.CallTheGaps.setTexts);

  await page.evaluate(
    (a, b) => {
      window.CallTheGaps.setTexts(a, b);
    },
    src,
    tgt
  );

  await page.waitForSelector(".error-chip");
  const chipCount = await page.$$eval(".error-chip", (els) => els.length);
  const types = await page.$$eval(".error-chip", (els) =>
    els.map((el) => el.getAttribute("data-change-type"))
  );
  assert(chipCount >= 3, "expected at least 3 error chips, got " + chipCount);
  assert(types.includes("insert"), "missing insert chip");
  assert(types.includes("delete"), "missing delete chip");
  assert(types.includes("move"), "missing move chip");

  async function clickType(type) {
    const sel = '.error-chip[data-change-type="' + type + '"]';
    await page.click(sel);
    await page.waitForFunction(
      (t) => {
        const chip = document.querySelector('.error-chip[data-change-type="' + t + '"].is-current');
        if (!chip) return false;
        const id = chip.getAttribute("data-change-id");
        return !!document.querySelector('.diff-pane__body [data-change-id="' + id + '"].is-active');
      },
      { timeout: 4000 },
      type
    );
    return page.evaluate((t) => {
      const chip = document.querySelector('.error-chip[data-change-type="' + t + '"].is-current');
      const id = chip.getAttribute("data-change-id");
      const marks = Array.from(
        document.querySelectorAll('.diff-pane__body [data-change-id="' + id + '"]')
      );
      const srcPane = document.getElementById("srcView");
      const tgtPane = document.getElementById("tgtView");
      function box(el) {
        const r = el.getBoundingClientRect();
        return { y: r.top, height: r.height, bottom: r.bottom };
      }
      const srcMark = marks.find((m) => srcPane.contains(m));
      const tgtMark = marks.find((m) => tgtPane.contains(m));
      return {
        id,
        type: t,
        markCount: marks.length,
        srcScroll: srcPane.scrollTop,
        tgtScroll: tgtPane.scrollTop,
        srcOverflow: srcPane.scrollHeight - srcPane.clientHeight,
        tgtOverflow: tgtPane.scrollHeight - tgtPane.clientHeight,
        srcVisible: srcMark
          ? box(srcMark).y + box(srcMark).height / 2 >= box(srcPane).y - 2 &&
            box(srcMark).y + box(srcMark).height / 2 <= box(srcPane).bottom + 2
          : null,
        tgtVisible: tgtMark
          ? box(tgtMark).y + box(tgtMark).height / 2 >= box(tgtPane).y - 2 &&
            box(tgtMark).y + box(tgtMark).height / 2 <= box(tgtPane).bottom + 2
          : null
      };
    }, type);
  }

  const del = await clickType("delete");
  assert(del.markCount >= 1, "delete should highlight a pane mark");
  assert(del.srcVisible === true, "delete mark should be visible in Precedent, got " + JSON.stringify(del));
  assert(del.srcOverflow > 40, "Precedent pane should overflow so jump can scroll");
  assert(del.srcScroll > 20, "delete jump should scroll Precedent, got " + del.srcScroll);

  const ins = await clickType("insert");
  assert(ins.markCount >= 1, "insert should highlight a pane mark");
  assert(ins.tgtVisible === true, "insert mark should be visible in Newer one, got " + JSON.stringify(ins));
  assert(ins.tgtScroll > 20, "insert jump should scroll Newer one, got " + ins.tgtScroll);

  const mv = await clickType("move");
  assert(mv.markCount >= 2, "move should highlight both panes, marks=" + mv.markCount);
  assert(mv.srcVisible === true, "move should be visible in Precedent, got " + JSON.stringify(mv));
  assert(mv.tgtVisible === true, "move should be visible in Newer one, got " + JSON.stringify(mv));
  assert(mv.srcScroll > 20, "move jump should scroll Precedent");
  assert(mv.tgtScroll > 20, "move jump should scroll Newer one");

  const afterSummary = await page.evaluate(async () => {
    document.querySelector('[data-jump-type="insert"]').click();
    await new Promise((r) => setTimeout(r, 50));
    return !!document.querySelector(".mark-insert.is-active");
  });
  assert(afterSummary, "summary insert chip should jump to an insert mark");

  await page.reload({ waitUntil: "networkidle0" });
  await page.waitForFunction(() => window.CallTheGaps);
  const srcInput = await page.$("#srcFile");
  const tgtInput = await page.$("#tgtFile");
  await srcInput.uploadFile("scripts/fixtures/gaps-source.docx");
  await tgtInput.uploadFile("scripts/fixtures/gaps-other.docx");
  await page.waitForSelector(".error-chip", { timeout: 15000 });
  await page.click(".error-chip");
  await page.waitForSelector(".diff-pane__body .is-active", { timeout: 4000 });
  const wordJump = await page.evaluate(() => {
    const chip = document.querySelector(".error-chip.is-current");
    const marks = document.querySelectorAll(".diff-pane__body .is-active");
    return {
      chipType: chip && chip.getAttribute("data-change-type"),
      markCount: marks.length
    };
  });
  assert(wordJump.markCount >= 1, "Word fixtures: chip click should highlight a pane mark");

  console.log("PASS", { chipCount, types, del, ins, mv, wordJump });
} finally {
  await browser.close();
}
