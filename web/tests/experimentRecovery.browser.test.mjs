import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";
import { timelineFixture } from "./fixtures/timeline.mjs";
import { withTaskAnswers } from "./taskAnswers.mjs";

let server;
let browser;
let origin;
before(async () => {
  server = await createServer({
    root: new URL("..", import.meta.url).pathname,
    logLevel: "silent",
    server: { host: "127.0.0.1", port: 0 },
  });
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
});
after(async () => {
  await browser?.close();
  await server?.close();
});

for (const scenario of ["retry", "resume", "switch provider"]) {
  const action = scenario === "resume" ? "resume" : "retry";
  test(
    `Experiment ${scenario} refreshes Runs before re-enabling recovery`,
    { timeout: 15000 },
    async (t) => {
      const context = await browser.newContext();
      t.after(() => context.close());
      const page = await context.newPage();
      page.setDefaultTimeout(10000);
      const errors = [];
      const unexpectedRequests = [];
      const submissions = [];
      page.on("requestfailed", (request) => {
        // The Terminals tab's projections are abandoned when the view unmounts
        // mid-flight. A deliberate abort is cleanup, not a failure.
        const aborted = new URL(request.url()).pathname;
        if (
          (aborted.endsWith("/terminals") || aborted.endsWith("/terminals/repositories")) &&
          request.failure()?.errorText === "net::ERR_ABORTED"
        )
          return;
        errors.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`);
      });
      page.on("response", (response) => {
        if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
      });
      page.on("console", (msg) => {
        if (msg.type() === "error") errors.push(msg.text());
      });
      page.on("pageerror", (error) => {
        errors.push(error.message);
      });
      const target = { kind: "main", branch_id: null };
      const node = {
        id: "exp/demo",
        type: "experiment",
        title: "Recovery experiment",
        status: "running",
        standing: "asserted",
        created_rev: 1,
        updated_rev: 1,
        source_refs: [],
        extension_fields: {},
        objective: "Check recovery",
        design: "",
        expected_outcomes: [],
        interpretation_rules: [],
        completion_criteria: [],
        invocation_ceiling: 5,
        attempts: [],
        current_summary: "",
        next_action: null,
      };
      const previous = withTaskAnswers({
        operation_id: "failed-task",
        project_id: "demo",
        kind: "node_chat",
        status: action === "retry" ? "failed" : "paused",
        attempt: 1,
        graph_target: target,
        episode_id: "episode",
        created_at: "2026-09-01T12:00:00Z",
        request: {
          patch_kind: "experiment_loop",
          control_node_id: node.id,
          control_episode_id: "episode",
          provider: "claude",
          model: "fable",
          run_on: "local",
          chat_id: "chat",
          mode: "work",
        },
      });
      previous.can_retry = action === "retry";
      previous.can_resume = action === "resume";
      const next = withTaskAnswers({
        ...previous,
        operation_id: "recovered-task",
        status: "running",
        can_retry: false,
        can_resume: false,
        can_pause: true,
        attempt: 2,
        parent_operation_id: previous.operation_id,
        created_at: "2026-09-01T12:01:00Z",
      });
      if (scenario === "switch provider")
        next.request = { ...next.request, provider: "codex", model: "" };
      let recovered = false;
      const refreshRequested = Promise.withResolvers();
      const releaseRefresh = Promise.withResolvers();
      t.after(() => releaseRefresh.resolve());
      const episode = () => ({
        episode_id: "episode",
        project_id: "demo",
        mode: "experiment_loop",
        control_node_id: node.id,
        graph_target: target,
        status: recovered ? "running" : "needs_action",
        ending: null,
        wrapup_state: "not_started",
        created_at: previous.created_at,
        updated_at: previous.created_at,
        current_operation_id: recovered ? next.operation_id : previous.operation_id,
        current_control_task_id: recovered ? next.operation_id : previous.operation_id,
        tasks: recovered ? [previous, next] : [previous],
        archived: false,
        can_archive: true,
        budget: {
          invocation_ceiling: 5,
          invocations_used: 1,
          invocations_remaining: 4,
          observed_input_tokens: 0,
          observed_generated_tokens: 0,
        },
        health: recovered ? "active" : "needs_action",
        run_section: recovered ? "running" : "actionable",
        live: recovered,
        can_stop: true,
        recommendation: recovered ? "continue" : action,
      });
      const control = () => ({
        episode_id: "episode",
        episode: episode(),
        ready: false,
        reasons: [],
        graph_reasons: [],
        governing_decisions: [],
        decision_drift: [],
        invocation_ceiling: 5,
        invocations_used: 1,
        invocations_remaining: 4,
        health: recovered ? "agent_active" : "needs_action",
        run_section: recovered ? "running" : "actionable",
        recommendation: recovered ? "wait" : action,
        task_control: recovered ? null : action,
        can_start: false,
        can_stop: true,
        can_switch_provider: !recovered,
        operational: {
          current_operation_id: recovered ? next.operation_id : previous.operation_id,
          current_active: recovered,
          task_active: recovered,
          episode_live: true,
          current_invocation: 1,
          session: {
            provider: "claude",
            model: "fable",
            run_on: "local",
            native_session_bound: true,
          },
        },
      });
      const profile = { provider: "claude", model: "fable", reasoning: "high", run_on: "local" };
      const providers = Object.fromEntries(
        ["claude", "codex"].map((provider) => [
          provider,
          {
            provider,
            label: provider === "claude" ? "Claude" : "Codex",
            installed: true,
            authenticated: true,
            models: [],
            runtimes: [],
          },
        ]),
      );
      const project = () => ({
        id: "demo",
        name: "Recovery project",
        revision: 1,
        graph_target: target,
        graph_head: { target, revision: 1, transition_id: null },
        snapshot_freshness: "fresh",
        home_space_id: "space",
        canonical_state: { remote: false, reachable: true },
        graph_mutation: { available: true, reason: null },
        run_on: "local",
        repositories: [],
        machines: [{ alias: "local", host: "" }],
        project_truth_scope: [],
        default_run_truth_scope: [],
        providers,
        agent_profiles: Object.fromEntries(
          ["seed", "refresh", "node_chat", "project_chat", "paper_coach", "orchestrator"].map(
            (k) => [k, profile],
          ),
        ),
        provider_readiness: { local: providers },
        provider_skill_inventories: {},
        skill_catalog: [],
        skill_defaults: {},
        experiment_control: { [node.id]: control() },
        attention: {
          pending_proposal_ids: [],
          open_blocker_ids: [],
          decisions_awaiting_choice_ids: [],
          proposal_actions: {},
          decision_prior_choices: {},
        },
        counts: {},
        graph: {
          revision: 1,
          nodes: { [node.id]: node },
          edges: {},
          proposals: {},
          glossary: {},
          ambiguities: {},
          ontology: { types: [], fields: [], relations: [] },
          validation_messages: [],
          belief_transitions: [],
          replay_status: "complete",
        },
        paper: { text: "", sections: [] },
        paper_coach: {},
        validation_messages: [],
      });
      await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname;
        let json = [];
        if (path === "/api/health")
          json = { status: "ok", space_id: "space", space_kind: "personal", instance_id: "test" };
        else if (path === "/api/identity")
          json = {
            space_id: "space",
            space_kind: "personal",
            user: { user_id: "human", display_name: "Researcher" },
          };
        else if (path === "/api/projects")
          json = [{ id: "demo", name: "Recovery project", revision: 1 }];
        else if (path === `/api/projects/demo/tasks/failed-task/${action}`) {
          submissions.push({
            method: route.request().method(),
            body: route.request().postDataJSON(),
          });
          recovered = true;
          json = next;
        } else if (path === "/api/projects/demo" || path.endsWith("/cached")) {
          if (recovered) {
            refreshRequested.resolve();
            await releaseRefresh.promise;
          }
          json = project();
        } else if (path.endsWith("/readiness")) json = project();
        else if (path.endsWith("/tasks")) json = recovered ? [next, previous] : [previous];
        else if (path.endsWith("/episodes")) json = [episode()];
        else if (path.endsWith("/chats")) json = { chats: [], next_cursor: null };
        else if (path.endsWith("/usage")) json = { tasks: [], totals: {}, by_provider: [] };
        else if (path.endsWith("/revision"))
          json = { revision: 1, graph_head: project().graph_head };
        else if (path === "/api/providers/logins") json = [];
        else if (path === "/api/update-notice")
          json = {
            space: "personal",
            status: "current",
            current_version: "0.4.2",
            latest_version: "0.4.2",
            checked_at: null,
            last_success_at: null,
            companion_ready: false,
            download_url: null,
            source_checkout: true,
            update_command: null,
          };
        else if (path.endsWith("/timeline"))
          json = timelineFixture(episode().episode_id, episode().mode);
        else if (
          ![
            "/api/projects/demo/watchers",
            "/api/projects/demo/history/summaries",
            "/api/projects/demo/transition-manifest",
            "/api/projects/demo/experiment-episodes",
            // The Terminals tab's visibility is a project-level fact, so both
            // projections it decides from load with the project on every view.
            // An open session keeps the tab even where none can be launched.
            "/api/projects/demo/terminals/repositories",
            "/api/projects/demo/terminals",
          ].includes(path)
        )
          unexpectedRequests.push(path);
        await route.fulfill({ json });
      });
      await page.goto(`${origin}/#/projects/demo?view=runs`);
      const recovery = page.locator(".experiment-run-actions").getByRole("button", {
        name: action === "retry" ? "Retry Claude" : "Resume Claude",
        exact: true,
      });
      await recovery.waitFor({ timeout: 10000 });
      if (scenario === "switch provider") {
        await page.getByRole("button", { name: "Switch provider…", exact: true }).click();
        await page
          .getByRole("dialog")
          .getByRole("combobox", { name: /^Provider/i })
          .selectOption("codex");
        await page.getByRole("button", { name: "Switch provider", exact: true }).click();
      } else {
        await recovery.click();
      }
      const busyRecovery = page.locator(".experiment-run-actions").getByRole("button", {
        name: action === "resume" ? "Resuming Claude…" : "Retrying Claude…",
        exact: true,
      });
      await busyRecovery.waitFor();
      await refreshRequested.promise;
      assert.equal(await busyRecovery.isDisabled(), true);
      const switchProvider = page.getByRole("button", { name: "Switch provider…", exact: true });
      assert.equal(await switchProvider.isDisabled(), true);
      await busyRecovery.evaluate((button) => button.click());
      await switchProvider.evaluate((button) => button.click());
      assert.equal(submissions.length, 1);
      assert.equal(submissions[0].method, "POST");
      if (scenario === "switch provider") assert.equal(submissions[0].body.provider, "codex");
      releaseRefresh.resolve();
      await page
        .locator(".experiment-run-detail")
        .getByText("Agent active", { exact: true })
        .waitFor();
      await recovery.waitFor({ state: "detached" });
      assert.equal(await recovery.count(), 0);
      assert.equal(submissions.length, 1);
      assert.deepEqual(unexpectedRequests, []);
      assert.deepEqual(errors, []);
    },
  );
}
