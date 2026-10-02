import assert from "node:assert/strict";
import test from "node:test";
import {
  hideResolvedCodexHandoffErrors,
  isInjectedCodexContext,
} from "../src/providerHistoryPresentation.ts";
import { reconstructTaskTranscript } from "../src/agentTasks.ts";
import { withTaskAnswers } from "./taskAnswers.mjs";

const environment = "<environment_context>\n<cwd>/example/repo</cwd>\n</environment_context>";
const instructions =
  "# AGENTS.md instructions for /example/repo\n\n<INSTRUCTIONS>\nInjected guidance.\n</INSTRUCTIONS>";
const injected = (text, role = "user") => ({ role, text });

test("only complete injected user records are hidden", () => {
  for (const text of [environment, instructions, ` \n${environment}\n${instructions}\n `]) {
    assert.equal(isInjectedCodexContext(injected(text)), true);
  }
  for (const text of [
    "My actual question",
    "",
    `Please explain this: ${environment}`,
    `${environment}\nNow work on my request.`,
    `${instructions}\nThis is my message.`,
    "<environment_context>unfinished",
    "<INSTRUCTIONS>My instructions</INSTRUCTIONS>",
    "# AGENTS.md instructions\nA question about the file",
  ]) {
    assert.equal(isInjectedCodexContext(injected(text)), false, text);
  }
  assert.equal(isInjectedCodexContext(injected(environment, "assistant")), false);
  assert.equal(isInjectedCodexContext(injected(instructions, "assistant")), false);
});

const diagnostic = "The continued native transcript changed source identity.";
const failed = withTaskAnswers({
  operation_id: "failed",
  project_id: "project",
  kind: "project_chat",
  status: "failed",
  native_session_id: "native",
  created_at: "2026-09-01T00:00:00Z",
  request: { chat_id: "chat", message: "Continue my session" },
  error: diagnostic,
});
const success = withTaskAnswers({
  ...failed,
  operation_id: "success",
  status: "succeeded",
  created_at: "2026-09-01T00:01:00Z",
  error: null,
  result: { messages: ["Done"] },
});

test("a later successful continuation hides only the old diagnostic in chat", () => {
  const tasks = [failed, success];
  const lines = reconstructTaskTranscript(tasks);
  assert.equal(lines.filter((line) => line.role === "error").length, 1);
  const visible = hideResolvedCodexHandoffErrors(lines, tasks);
  assert.equal(visible.filter((line) => line.role === "error").length, 0);
  assert.equal(visible.filter((line) => line.role === "human").length, 2);
  assert.equal(visible.find((line) => line.role === "agent").text, "Done");
  assert.equal(failed.error, diagnostic);
  assert.equal(failed.failed, true);
  const quoted = { ...lines.find((line) => line.role === "error"), role: "agent" };
  assert.deepEqual(hideResolvedCodexHandoffErrors([quoted], tasks), [quoted]);
});

test("unresolved, unrelated and newer failures remain visible", () => {
  const error = reconstructTaskTranscript([failed]).find((line) => line.role === "error");
  const candidates = [
    [],
    [withTaskAnswers({ ...success, status: "running" })],
    [withTaskAnswers({ ...success, status: "failed" })],
    [{ ...success, created_at: failed.created_at }],
    [{ ...success, created_at: "2026-08-31T00:00:00Z" }],
    [{ ...success, native_session_id: "other" }],
    [{ ...success, project_id: "other" }],
    [{ ...success, request: { chat_id: "other" } }],
  ];
  for (const later of candidates) {
    assert.deepEqual(hideResolvedCodexHandoffErrors([error], [failed, ...later]), [error]);
  }
  const otherError = { ...error, text: "Repository write failed" };
  assert.deepEqual(hideResolvedCodexHandoffErrors([otherError], [failed, success]), [otherError]);
  assert.deepEqual(hideResolvedCodexHandoffErrors([error], [success]), [error]);
});
