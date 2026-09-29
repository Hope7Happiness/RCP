import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("narrow Chats and DAG keep the working surface primary behind accessible disclosures", async (t) => {
  const server = await createServer({
    root: new URL("..", import.meta.url).pathname,
    logLevel: "error",
    server: { host: "127.0.0.1", port: 0 },
  });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true });
    const base = `http://127.0.0.1:${server.httpServer.address().port}/tests/fixtures`;
    for (const viewport of [
      { width: 390, height: 844 },
      { width: 360, height: 780 },
    ]) {
      const page = await browser.newPage({ viewport, reducedMotion: "reduce" });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("requestfailed", (request) => errors.push(request.url()));
      await page.route("**/api/projects/project/chats/*/worktree**", (route) =>
        route.fulfill({ json: { show_chooser: false, binding: null, integration_options: [] } }),
      );
      await page.route("**/api/projects/*/chat-display", (route) =>
        route.fulfill({ json: { archived: [], titles: {} } }),
      );
      await page.route("**/api/projects/*/provider-history", (route) =>
        route.fulfill({ json: [] }),
      );
      await page.route("**/api/projects/fixture/graph-edit-options", (route) =>
        route.fulfill({ json: { node_prefixes: {}, relations: [] } }),
      );

      await page.goto(`${base}/mobileChats.html`);
      const composer = page.getByRole("textbox", { name: "Message", exact: true });
      await composer.waitFor();
      const list = page.locator(".conversation-list");
      const chatToggle = page.getByRole("button", { name: "Agents", exact: true });
      assert.equal(await list.isVisible(), false, "Mobile conversation list starts closed");
      assert.equal(await page.getByRole("separator").count(), 0, "No narrow resize strip");
      const composerWidth = (await composer.boundingBox()).width;
      assert.ok(composerWidth >= viewport.width - 50, "Composer uses the full narrow column");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width);
      await composer.fill("A draft survives opening the conversation list.");
      await chatToggle.focus();
      await page.keyboard.press("Enter");
      await list.waitFor();
      assert.equal(await composer.inputValue(), "A draft survives opening the conversation list.");
      assert.equal((await composer.boundingBox()).width, composerWidth);
      assert.ok(
        (await composer.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))) >=
          16,
        "A focused field is at least 16px, so iOS does not zoom the page",
      );
      for (const height of await list
        .locator('[role="option"], input[type="search"], .agent-list-filters button')
        .evaluateAll((controls) =>
          controls.map((control) => control.getBoundingClientRect().height),
        )) {
        assert.ok(height >= 44, `Panel controls are at least 44px tall, got ${height}`);
      }
      await page.getByRole("option", { name: "Second chat, project conversation" }).click();
      await list.waitFor({ state: "hidden" });
      await chatToggle.click();
      assert.equal(
        await page
          .getByRole("option", { name: "Second chat, project conversation" })
          .getAttribute("aria-selected"),
        "true",
      );
      await chatToggle.click();
      await list.waitFor({ state: "hidden" });

      await page.setViewportSize({ width: 1100, height: 900 });
      await list.waitFor();
      const resize = page.getByRole("separator", { name: "Resize conversation list" });
      const widthBeforeResize = Number(await resize.getAttribute("aria-valuenow"));
      await resize.focus();
      await page.keyboard.press("ArrowRight");
      await page.waitForFunction(
        (width) =>
          Number(
            document.querySelector(".conversation-resize-handle").getAttribute("aria-valuenow"),
          ) > width,
        widthBeforeResize,
      );
      const desktopWidth = Number(await resize.getAttribute("aria-valuenow"));
      await page.waitForFunction(
        (width) =>
          document.querySelector(".conversation-list").getBoundingClientRect().width === width,
        desktopWidth,
      );
      await page.getByRole("button", { name: "Collapse conversation list" }).click();
      await list.waitFor({ state: "hidden" });
      await page.setViewportSize(viewport);
      await chatToggle.waitFor();
      await chatToggle.click();
      await list.waitFor();
      await page.setViewportSize({ width: 1100, height: 900 });
      await list.waitFor({ state: "hidden" });
      await page.getByRole("button", { name: "Expand conversation list" }).click();
      await list.waitFor();
      assert.equal(
        await page
          .locator(".conversation-list")
          .evaluate((element) => element.getBoundingClientRect().width),
        desktopWidth,
        "Narrow disclosure does not overwrite the desktop resize preference",
      );

      await page.setViewportSize(viewport);
      await page.goto(`${base}/dagViewport.html?representative`);
      await page.locator(".dag-node").last().waitFor();
      const dagToggle = page.locator(".dag-controls-disclosure > summary");
      const controls = page.locator(".dag-controls");
      assert.equal(await controls.isVisible(), false, "DAG controls start closed on mobile");
      const canvasTop = (await page.locator(".dag-scroll").boundingBox()).y;
      assert.ok(canvasTop < viewport.height / 3, "Canvas begins in the top third of the fixture");
      await dagToggle.focus();
      await page.keyboard.press("Enter");
      await controls.waitFor();
      await page.getByRole("button", { name: "Research flow", exact: true }).click();
      assert.equal(
        await page
          .getByRole("button", { name: "Research flow", exact: true })
          .getAttribute("aria-pressed"),
        "true",
      );
      await dagToggle.click();
      await controls.waitFor({ state: "hidden" });
      assert.equal((await page.locator(".dag-scroll").boundingBox()).y, canvasTop);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width);
      await page.setViewportSize({ width: 1100, height: 900 });
      await controls.waitFor();
      assert.equal(await dagToggle.isVisible(), false, "Desktop controls remain directly visible");
      assert.deepEqual(errors, []);
      t.diagnostic(
        `${viewport.width}x${viewport.height}: composer ${composerWidth}px; canvas top ${canvasTop}px (component fixtures).`,
      );
      await page.close();
    }
  } finally {
    await browser?.close();
    await server.close();
  }
});
