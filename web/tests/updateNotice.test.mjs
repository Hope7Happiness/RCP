import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "vite";
import { chromium } from "playwright";

const fixture = {
  space: "personal",
  status: "update_available",
  current_version: "0.4.2",
  latest_version: "0.4.3",
  checked_at: "2026-09-26T12:00:00Z",
  last_success_at: null,
  companion_ready: false,
  download_url: null,
  source_checkout: true,
  update_command: "scripts/update-from-source v0.4.3",
};

test("release notice transitions, actions, visibility, and storage through a served React surface", async (t) => {
  const server = await createServer({
    root: new URL("..", import.meta.url).pathname,
    logLevel: "silent",
    // A private optimizer cache: this server re-crawls after reloads and must
    // not rewrite the shared cache that parallel browser tests are serving from.
    cacheDir: mkdtempSync(join(tmpdir(), "rcp-update-notice-vite-")),
    server: { host: "127.0.0.1", port: 0 },
  });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.setDefaultTimeout(10_000);
    let data = { ...fixture, status: "unchecked" };
    let reads = 0;
    await page.route("**/api/update-notice", (route) => {
      reads++;
      return route.fulfill({ json: data });
    });
    await page.goto(`${server.resolvedUrls.local[0]}tests/fixtures/updateNotice.html`);
    await page.waitForFunction(() => document.querySelector('[data-status="unchecked"]'));
    const refresh = async (identity) => {
      const before = reads;
      await page.evaluate((identity) => {
        if (identity !== undefined) window.identity = identity;
        window.visibility.dispatchEvent(new Event("visibilitychange"));
      }, identity);
      await page.waitForFunction(() => document.querySelector("[data-status]"));
      await page.evaluate(
        () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      );
      assert.ok(reads > before);
    };
    await t.test(
      "kinds select native downloads and exact copy commands as data changes",
      async () => {
        data = { ...fixture };
        await refresh();
        await page.locator('[data-kind="prebuilt"]').waitFor();
        assert.equal(await page.locator("[data-kind] a").count(), 0);
        // Dismissing before the download exists must not hide the later download.
        await page.locator(".desktop-update-dismiss").click();
        await page.locator('[data-kind="prebuilt"]').waitFor({ state: "detached" });
        data = {
          ...fixture,
          companion_ready: true,
          download_url: "https://example.invalid/releases/desktop-v0.4.3",
        };
        await refresh();
        await page.locator("[data-kind] a").waitFor();
        assert.equal(await page.locator("[data-kind] a").getAttribute("href"), data.download_url);
        assert.equal(await page.locator("[data-kind] a").getAttribute("target"), "_blank");
        data = { ...fixture, space: "team", update_command: "sudo rcp server update" };
        await refresh();
        await page.locator('[data-kind="team"] code').waitFor();
        await page.locator("[data-kind] button.secondary").click();
        assert.equal(await page.evaluate(() => window.copied.at(-1)), data.update_command);
        data = { ...fixture };
        await refresh({ kind: "source", version: "0.4.2", checkout: "/fixture" });
        await page.locator('[data-kind="source"] code').waitFor();
        await page.locator("[data-kind] button.secondary").click();
        assert.equal(
          await page.evaluate(() => window.copied.at(-1)),
          data.update_command + " --desktop",
        );
        await refresh(null);
        await page.locator("[data-kind] button.secondary").click();
        assert.equal(await page.evaluate(() => window.copied.at(-1)), data.update_command);
        assert.equal(await page.evaluate(() => window.readIdentity()), null);
        const native = await page.evaluate(async () => {
          const calls = [];
          window.__TAURI_INTERNALS__ = {
            invoke: async (command) => {
              calls.push(command);
              return { kind: "source", version: "0.4.2", checkout: "/fixture" };
            },
          };
          try {
            return { identity: await window.readIdentity(), calls };
          } finally {
            delete window.__TAURI_INTERNALS__;
          }
        });
        assert.deepEqual(native.calls, ["desktop_build_identity"]);
        assert.equal(native.identity.kind, "source");
      },
    );
    await t.test("non-update statuses remain inspectable without a notice", async () => {
      for (const status of ["current", "pinned", "unchecked", "failed", "off", "unknown"]) {
        data = { ...fixture, status };
        await refresh();
        await page.waitForFunction(
          (status) => document.querySelector("[data-status]")?.dataset.status === status,
          status,
        );
        assert.equal(await page.locator("[data-kind]").count(), 0);
      }
    });
    await t.test("dismissal persists per release and survives unavailable storage", async () => {
      data = { ...fixture };
      await refresh();
      await page.locator(".desktop-update-dismiss").click();
      assert.equal(await page.locator("[data-kind]").count(), 0);
      assert.equal(
        await page.evaluate(() => localStorage.getItem("rcp:update-dismissed:source:0.4.3")),
        "1",
      );
      await page.reload();
      await page.waitForFunction(
        () => document.querySelector("[data-status]")?.dataset.status === "update_available",
      );
      assert.equal(await page.locator("[data-kind]").count(), 0);
      data = { ...fixture, latest_version: "0.4.4" };
      await refresh();
      await page.locator("[data-kind]").waitFor();
      await page.evaluate(() => {
        Object.defineProperty(window, "localStorage", {
          get() {
            throw new Error("unavailable");
          },
        });
      });
      await page.locator(".desktop-update-dismiss").click();
      await page.evaluate(() => window.remount());
      await page.waitForFunction(
        () => document.querySelector("[data-status]")?.dataset.status === "update_available",
      );
      await refresh();
      assert.equal(await page.locator("[data-kind]").count(), 0);
      data = { ...fixture, latest_version: "0.4.5" };
      await refresh();
      await page.locator("[data-kind]").waitFor();
    });
    await t.test("hidden documents stop fetching and visibility restores polling", async () => {
      const before = reads;
      await page.evaluate(() => {
        window.visibility.visibilityState = "hidden";
        window.visibility.dispatchEvent(new Event("visibilitychange"));
      });
      assert.equal(reads, before);
      await page.evaluate(() => {
        window.visibility.visibilityState = "visible";
      });
      await refresh();
    });
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});

test("poll scheduling follows cache status and stops on cleanup", async () => {
  const server = await createServer({
    root: new URL("..", import.meta.url).pathname,
    configFile: false,
    logLevel: "silent",
    server: { middlewareMode: true, hmr: false },
    optimizeDeps: { noDiscovery: true },
  });
  try {
    const { startUpdateNoticePolling, UPDATE_NOTICE_UNCHECKED_POLL_MS, UPDATE_NOTICE_POLL_MS } =
      await server.ssrLoadModule("/src/hooks/useUpdateNotice.ts");
    const visibility = new EventTarget();
    visibility.visibilityState = "visible";
    let scheduled;
    let data = { ...fixture, status: "unchecked" };
    const received = [];
    const clock = {
      setTimeout(callback, delay) {
        scheduled = { callback, delay };
        return 1;
      },
      clearTimeout() {
        scheduled = null;
      },
    };
    const stop = startUpdateNoticePolling(
      async () => data,
      (value) => received.push(value),
      visibility,
      clock,
    );
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(scheduled.delay, UPDATE_NOTICE_UNCHECKED_POLL_MS);
    data = fixture;
    scheduled.callback();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(scheduled.delay, UPDATE_NOTICE_POLL_MS);
    assert.equal(received.length, 2);
    // A route answered by an older server or an error body is not a notice.
    data = [];
    scheduled.callback();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(received.length, 2);
    stop();
    assert.equal(scheduled, null);
    visibility.dispatchEvent(new Event("visibilitychange"));
    assert.equal(received.length, 2);
  } finally {
    await server.close();
  }
});
