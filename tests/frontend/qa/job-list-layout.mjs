import { chromium } from "../../../frontend/node_modules/playwright/index.mjs";
import assert from "node:assert/strict";

const browser = await chromium.launch({ channel: "msedge", headless: true });
const base = process.env.QA_BASE_URL || "http://127.0.0.1:5173";
try {
  for (const width of [1280, 1024, 970, 950, 390]) {
    for (const scenario of ["pair", "long"]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.goto(`${base}/admin/data?qa=${scenario}`);
      await page.getByText("검색 결과", { exact: false }).first().waitFor();
      const result = await page.locator("#cleanup-list").evaluate(root => {
        const visible = [...root.querySelectorAll(".jobs-table-scroll, .jobs-mobile-list")]
          .find(element => getComputedStyle(element).display !== "none");
        const elements = [visible, ...visible.querySelectorAll("*")];
        const overflow = elements.filter(element => {
          const style = getComputedStyle(element);
          return ((/(auto|scroll)/.test(style.overflowX) && element.scrollWidth > element.clientWidth + 1)
            || (/(auto|scroll)/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 1));
        }).map(element => ({ tag: element.tagName, className: element.className, client: [element.clientWidth, element.clientHeight], scroll: [element.scrollWidth, element.scrollHeight] }));
        const buttons = [...visible.querySelectorAll("button")].filter(button => button.textContent.includes("상세 조회"));
        const copyButtons = [...visible.querySelectorAll(".jobs-id button")];
        return { layout: visible.className, overflow, count: buttons.length,
          copyClipped: copyButtons.some(button => button.getBoundingClientRect().width < 36 || button.querySelector("svg").getBoundingClientRect().width < 13),
          clipped: buttons.some(button => {
          const box = button.getBoundingClientRect(), area = visible.getBoundingClientRect();
          const text = button.querySelector("[data-direction=horizontal]");
          return box.left < area.left - 1 || box.right > area.right + 1 || box.bottom > area.bottom + 1 || text.scrollWidth > text.clientWidth + 1 || text.getBoundingClientRect().height > 30;
        }) };
      });
      assert.equal(result.layout, width <= 950 ? "jobs-mobile-list" : "jobs-table-scroll", `${width}/${scenario}: 목록 구성`);
      assert.deepEqual(result.overflow, [], `${width}/${scenario}: ${JSON.stringify(result.overflow)}`);
      assert.equal(result.count, scenario === "long" ? 25 : 2);
      assert.equal(result.clipped, false, `${width}/${scenario}: 상세 조회 잘림`);
      assert.equal(result.copyClipped, false, `${width}/${scenario}: 복사 버튼 잘림`);
      if (scenario === "long") {
        assert.equal(await page.evaluate(() => { window.scrollTo(0, 500); return window.scrollY > 0; }), true, `${width}: 페이지 스크롤`);
      }
      await page.getByRole("button", { name: /상세 조회/ }).first().click();
      await page.getByRole("dialog", { name: "작업 상세" }).waitFor();
      await page.close();
    }
  }
  console.log("작업 목록 레이아웃 검사 통과");
} finally {
  await browser.close();
}
