import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ImportedHistoryPage, ImportedHistorySummary } from "../types";

const PAGE_SIZE = 100;

export function ProviderHistory({
  apiBase,
  writesDisabled = false,
  sessionId: displayedSessionId,
  onImported,
}: {
  apiBase: string;
  writesDisabled?: boolean;
  /** When set, render one selected session as a read-only Agents detail. */
  sessionId?: string;
  onImported?: (summary: ImportedHistorySummary) => void;
}) {
  const inAgents = displayedSessionId !== undefined;
  const [imports, setImports] = useState<ImportedHistorySummary[]>([]);
  const [selected, setSelected] = useState<string | null>(displayedSessionId ?? null);
  const [page, setPage] = useState<ImportedHistoryPage | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <section
      className={`settings-section provider-history-settings${inAgents ? " provider-history-agents" : ""}`}
    >
      <header>
        <h2>{inAgents ? "Imported Codex session" : "Imported Codex history"}</h2>
      </header>
      <p>
        A read-only snapshot of native Codex messages. These messages are not RCP task turns and
        grant no graph or file permissions. Refresh the snapshot to include later messages.
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
