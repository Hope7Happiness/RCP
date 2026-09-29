import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("Agents shows imported history and can request a controlled Codex continuation", async () => {
  const server = await createServer({
    root: new URL("..", import.meta.url).pathname,
    logLevel: "error",
    server: { host: "127.0.0.1", port: 0 },
  });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("requestfailed", (request) => errors.push(request.url()));
    const sessionId = "11111111-1111-4111-8111-111111111111";
    const continuationRequests = [];
    let refreshed = false;
    const summary = {
      provider: "codex",
      session_id: sessionId,
      source_sha256: "a".repeat(64),
      source_bytes: 1024,
      repository_alias: "repo",
      first_timestamp: "2026-09-29T00:00:00Z",
      last_timestamp: "2026-09-29T00:00:01Z",
      imported_at: "2026-09-29T00:00:02Z",
      message_count: 2,
    };
    await page.route("**/api/projects/project/provider-history", (route) =>
      route.fulfill({ json: [{ ...summary, message_count: refreshed ? 3 : 2 }] }),
    );
    await page.route("**/api/projects/project/provider-history/codex", async (route) => {
      refreshed = true;
      await route.fulfill({ json: { ...summary, message_count: 3 } });
    });
    await page.route("**/api/projects/project/provider-history/codex/*/source-status", (route) =>
      route.fulfill({ json: { source_bytes: 1030, imported_bytes: refreshed ? 1030 : 1024 } }),
    );
    await page.route("**/api/projects/project/provider-history/codex/*", (route) =>
      route.fulfill({
        json: {
          ...summary,
          message_count: refreshed ? 3 : 2,
          offset: 0,
          limit: 100,
          messages: [
            {
              message_id: "one",
              role: "user",
              phase: null,
              timestamp: "2026-09-29T00:00:00Z",
              text: "Earlier question",
            },
            {
              message_id: "two",
              role: "assistant",
              phase: "final_answer",
              timestamp: "2026-09-29T00:00:01Z",
              text: "Earlier answer",
            },
            ...(refreshed
              ? [
                  {
                    message_id: "three",
                    role: "assistant",
                    phase: "final_answer",
                    timestamp: "2026-09-29T00:00:03Z",
                    text: "Later Herdr message",
                  },
                ]
              : []),
          ],
        },
      }),
    );
    await page.route("**/api/projects/project/provider-history/codex/*/continue", async (route) => {
      continuationRequests.push(route.request().postDataJSON());
      if (continuationRequests.length === 1) {
        await route.fulfill({
          status: 409,
          json: {
            detail:
              "Codex session is active in Herdr pane w9:p2. Quit it in Herdr before retrying.",
          },
        });
      } else {
        await route.fulfill({
          json: { chat_id: "continued-chat", task: { operation_id: "task-1" } },
        });
      }
    });
    await page.route("**/api/projects/*/chat-display", (route) =>
      route.fulfill({ json: { archived: [], titles: {} } }),
    );
    await page.route("**/api/projects/project/chats/*/worktree**", (route) =>
      route.fulfill({ json: { show_chooser: false, binding: null, integration_options: [] } }),
    );
    await page.route("**/api/projects/fixture/graph-edit-options", (route) =>
      route.fulfill({ json: { node_prefixes: {}, relations: [] } }),
    );

    await page.goto(
      `http://127.0.0.1:${server.httpServer.address().port}/tests/fixtures/mobileChats.html`,
    );
    const imported = page.getByRole("option", {
      name: `Imported Codex session ${sessionId}`,
    });
    await imported.waitFor();
    assert.equal(await page.locator('[data-filter="all"]').innerText(), "All 3");
    assert.equal(await page.locator('[data-filter="imported"]').innerText(), "Imported 1");
    await page.locator('[data-filter="imported"]').click();
    assert.equal(await page.getByRole("option").count(), 1);
    await imported.click();
    await page.getByText("Earlier answer", { exact: true }).waitFor();
    await page.getByText("Later Herdr message", { exact: true }).waitFor();
    assert.equal(await page.locator(".provider-history-message").count(), 3);
    assert.equal(await page.getByRole("textbox", { name: "Message", exact: true }).count(), 0);
    await page
      .getByRole("textbox", { name: "Message to continue Codex session" })
      .fill("Next step");
    await page.getByRole("button", { name: "Continue session" }).click();
    await page
      .getByRole("alert")
      .getByText(/Herdr pane w9:p2/)
      .waitFor();
    assert.deepEqual(continuationRequests, [{ message: "Next step", mode: "discuss" }]);
    await page.getByRole("radio", { name: /Work/ }).check();
    await page.getByRole("button", { name: "Continue session" }).click();
    await page.getByTestId("continued-chat").filter({ hasText: "continued-chat" }).waitFor();
    assert.deepEqual(continuationRequests, [
      { message: "Next step", mode: "discuss" },
      { message: "Next step", mode: "work" },
    ]);
    assert.equal(
      await page.getByRole("textbox", { name: "Message to continue Codex session" }).count(),
      0,
    );
    await imported.click();
    await page.getByRole("button", { name: "Open RCP chat" }).waitFor();
    assert.equal(
      await page.getByRole("textbox", { name: "Message to continue Codex session" }).count(),
      0,
    );
    assert.deepEqual(
      errors.filter((error) => !error.includes("409 (Conflict)")),
      [],
    );
    await page.close();
  } finally {
    await browser?.close();
    await server.close();
  }
});
