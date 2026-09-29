import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AgentTask, ImportedHistoryPage, ImportedHistorySummary } from "../types";

const PAGE_SIZE = 100;

export interface ImportedContinuation {
  chat_id: string;
  task: AgentTask;
}

export function ProviderHistory({
  apiBase,
  writesDisabled = false,
  sessionId: displayedSessionId,
  continuedChatId,
  onImported,
  onContinued,
  onOpenContinuedChat,
}: {
  apiBase: string;
  writesDisabled?: boolean;
  /** When set, render one selected session in the Agents workspace. */
  sessionId?: string;
  continuedChatId?: string;
  onImported?: (summary: ImportedHistorySummary) => void;
  onContinued?: (result: ImportedContinuation) => Promise<void> | void;
  onOpenContinuedChat?: () => void;
}) {
  const inAgents = displayedSessionId !== undefined;
  const [imports, setImports] = useState<ImportedHistorySummary[]>([]);
  const [selected, setSelected] = useState<string | null>(displayedSessionId ?? null);
  const [page, setPage] = useState<ImportedHistoryPage | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<"discuss" | "work">("discuss");
  const importedCallback = useRef(onImported);
  importedCallback.current = onImported;

  const refreshList = useCallback(async () => {
    const loaded = await api<ImportedHistorySummary[]>(`${apiBase}/provider-history`);
    setImports(loaded);
    setSelected((current) =>
      inAgents
        ? displayedSessionId
        : current && loaded.some((item) => item.session_id === current)
          ? current
          : (loaded[0]?.session_id ?? null),
    );
  }, [apiBase, displayedSessionId, inAgents]);

  const loadPage = useCallback(
    async (id: string, offset: number) => {
      setPage(
        await api<ImportedHistoryPage>(
          `${apiBase}/provider-history/codex/${encodeURIComponent(id)}?offset=${offset}&limit=${PAGE_SIZE}`,
        ),
      );
    },
    [apiBase],
  );

  useEffect(() => {
    void refreshList().catch((failure) =>
      setError(failure instanceof Error ? failure.message : String(failure)),
    );
  }, [refreshList]);

  useEffect(() => {
    if (!selected) {
      setPage(null);
      return;
    }
    setPage(null);
    void loadPage(selected, 0).catch((failure) =>
      setError(failure instanceof Error ? failure.message : String(failure)),
    );
  }, [selected, loadPage]);

  useEffect(() => {
    if (!inAgents || !selected || writesDisabled || busy) return;
    let inFlight = false;
    let lastAttemptedSize: number | null = null;
    const sync = async () => {
      if (inFlight || document.visibilityState === "hidden") return;
      inFlight = true;
      try {
        const status = await api<{ source_bytes: number; imported_bytes: number }>(
          `${apiBase}/provider-history/codex/${encodeURIComponent(selected)}/source-status`,
        );
        if (
          status.source_bytes > status.imported_bytes &&
          status.source_bytes !== lastAttemptedSize
        ) {
          lastAttemptedSize = status.source_bytes;
          const saved = await api<ImportedHistorySummary>(`${apiBase}/provider-history/codex`, {
            method: "POST",
            body: JSON.stringify({ session_id: selected }),
          });
          importedCallback.current?.(saved);
          await refreshList();
          await loadPage(selected, page?.offset ?? 0);
        }
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : String(failure));
      } finally {
        inFlight = false;
      }
    };
    void sync();
    const timer = window.setInterval(() => void sync(), 20_000);
    return () => window.clearInterval(timer);
  }, [apiBase, busy, inAgents, loadPage, page?.offset, refreshList, selected, writesDisabled]);

  async function importSession(id: string) {
    setBusy(true);
    setError(null);
    try {
      const saved = await api<ImportedHistorySummary>(`${apiBase}/provider-history/codex`, {
        method: "POST",
        body: JSON.stringify({ session_id: id }),
      });
      onImported?.(saved);
      await refreshList();
      setSelected(id);
      await loadPage(id, 0);
      setSessionId("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  async function continueSession(id: string) {
    const text = message.trim();
    if (!text || !onContinued) return;
    setBusy(true);
    setError(null);
    let started = false;
    try {
      const result = await api<ImportedContinuation>(
        `${apiBase}/provider-history/codex/${encodeURIComponent(id)}/continue`,
        { method: "POST", body: JSON.stringify({ message: text, mode }) },
      );
      started = true;
      setMessage("");
      await onContinued(result);
    } catch (failure) {
      const reason = failure instanceof Error ? failure.message : String(failure);
      setError(
        started ? `Turn started, but the conversation could not be opened: ${reason}` : reason,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={`settings-section provider-history-settings${inAgents ? " provider-history-agents" : ""}`}
    >
      <header>
        <h2>{inAgents ? "Codex session" : "Imported Codex history"}</h2>
      </header>
      <p>
        The messages below are a snapshot of native Codex history. They are not RCP task turns and
        grant no graph or file permissions. Messages sent directly in Herdr appear here after the
        visible session refreshes or you press Refresh snapshot; they do not become RCP task turns.
      </p>
      {!inAgents ? (
        <form
          className="provider-history-import"
          onSubmit={(event) => {
            event.preventDefault();
            const id = sessionId.trim();
            if (id) void importSession(id);
          }}
        >
          <input
            aria-label="Codex session ID"
            placeholder="Codex session ID"
            value={sessionId}
            disabled={busy || writesDisabled}
            onChange={(event) => setSessionId(event.target.value)}
          />
          <button
            className="button compact"
            type="submit"
            disabled={busy || writesDisabled || !sessionId.trim()}
          >
            Import session
          </button>
        </form>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      {imports.length > 0 ? (
        <div className="provider-history-selection">
          {inAgents ? (
            <strong>{selected}</strong>
          ) : (
            <label>
              Session
              <select value={selected ?? ""} onChange={(event) => setSelected(event.target.value)}>
                {imports.map((item) => (
                  <option key={item.session_id} value={item.session_id}>
                    {item.repository_alias} · {item.session_id}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            className="button secondary compact"
            type="button"
            disabled={!selected || busy || writesDisabled}
            onClick={() => selected && void importSession(selected)}
          >
            Refresh snapshot
          </button>
        </div>
      ) : (
        <p>No Codex session has been imported into this project.</p>
      )}
      {inAgents &&
      selected &&
      imports.some((item) => item.session_id === selected) &&
      continuedChatId &&
      onOpenContinuedChat ? (
        <div className="provider-history-continue">
          <p>This native session now belongs to an RCP chat. Send its next turn there.</p>
          <button className="button primary compact" type="button" onClick={onOpenContinuedChat}>
            Open RCP chat
          </button>
        </div>
      ) : inAgents &&
        selected &&
        imports.some((item) => item.session_id === selected) &&
        onContinued ? (
        <form
          className="provider-history-continue"
          onSubmit={(event) => {
            event.preventDefault();
            void continueSession(selected);
          }}
        >
          <h3>Continue this Codex session</h3>
          <p>
            The next RCP turn resumes this native session in a managed Herdr pane. An existing Codex
            process must release the session first. Choose Work explicitly to allow bounded project
            writes and commands; Discuss is read only.
          </p>
          <fieldset disabled={busy || writesDisabled}>
            <legend>Permission for the next turn</legend>
            <label>
              <input
                checked={mode === "discuss"}
                name="imported-continuation-mode"
                onChange={() => setMode("discuss")}
                type="radio"
                value="discuss"
              />
              Discuss · read only
            </label>
            <label>
              <input
                checked={mode === "work"}
                name="imported-continuation-mode"
                onChange={() => setMode("work")}
                type="radio"
                value="work"
              />
              Work · project scoped writes and commands
            </label>
          </fieldset>
          <textarea
            aria-label="Message to continue Codex session"
            disabled={busy || writesDisabled}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="What should Codex do next?"
            rows={4}
            style={{ display: "block", maxWidth: "100%", width: "100%" }}
            value={message}
          />
          <button
            className="button primary compact"
            disabled={busy || writesDisabled || !message.trim()}
            type="submit"
          >
            {busy ? "Starting…" : "Continue session"}
          </button>
        </form>
      ) : null}
      {page ? (
        <div className="provider-history-messages">
          <p>
            {page.message_count} messages · through {page.last_timestamp ?? "unknown"} · imported{" "}
            {page.imported_at}
          </p>
          <div className="provider-history-page-controls">
            <button
              className="button secondary compact"
              type="button"
              disabled={page.offset === 0}
              onClick={() =>
                selected && void loadPage(selected, Math.max(0, page.offset - PAGE_SIZE))
              }
            >
              Previous
            </button>
            <span>
              {page.offset + 1}–{Math.min(page.offset + page.messages.length, page.message_count)}{" "}
              of {page.message_count}
            </span>
            <button
              className="button secondary compact"
              type="button"
              disabled={page.offset + page.messages.length >= page.message_count}
              onClick={() => selected && void loadPage(selected, page.offset + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
          {page.messages.map((message) => (
            <article className="provider-history-message" key={message.message_id}>
              <header>
                <strong>{message.role === "user" ? "Codex user" : "Codex assistant"}</strong>
                {message.phase ? (
                  <span>{message.phase === "final_answer" ? "Final answer" : "Commentary"}</span>
                ) : null}
                <time dateTime={message.timestamp}>{message.timestamp}</time>
              </header>
              <pre>{message.text}</pre>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
