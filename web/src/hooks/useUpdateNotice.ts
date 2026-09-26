import { useEffect, useState } from "react";
import { loadUpdateNotice } from "../api";
import type { UpdateNotice } from "../types";

export const UPDATE_NOTICE_UNCHECKED_POLL_MS = 30_000;
export const UPDATE_NOTICE_POLL_MS = 10 * 60_000;

export interface UpdateVisibility {
  readonly visibilityState: string;
  addEventListener(type: "visibilitychange", listener: () => void): void;
  removeEventListener(type: "visibilitychange", listener: () => void): void;
}
interface PollClock {
  setTimeout(callback: () => void, delay: number): number;
  clearTimeout(id: number): void;
}
const STATUSES = new Set<UpdateNotice["status"]>([
  "update_available",
  "current",
  "pinned",
  "unchecked",
  "failed",
  "off",
  "unknown",
]);

// An older server without this route, or an error page, must not reach the
// notice or the Settings rows as if it were one.
export function isUpdateNotice(value: unknown): value is UpdateNotice {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const notice = value as Record<string, unknown>;
  return (
    (notice.space === "team" || notice.space === "personal") &&
    STATUSES.has(notice.status as UpdateNotice["status"]) &&
    typeof notice.companion_ready === "boolean" &&
    typeof notice.source_checkout === "boolean"
  );
}

export function startUpdateNoticePolling(
  load: () => Promise<UpdateNotice>,
  receive: (notice: UpdateNotice) => void,
  visibility: UpdateVisibility,
  clock: PollClock,
) {
  let stopped = false;
  let pending = false;
  let timer = 0;
  let status: UpdateNotice["status"] = "unchecked";
  const poll = async () => {
    clock.clearTimeout(timer);
    if (stopped || pending || visibility.visibilityState !== "visible") return;
    pending = true;
    try {
      const notice: unknown = await load();
      if (isUpdateNotice(notice)) {
        status = notice.status;
        if (!stopped) receive(notice);
      }
    } catch {
      // The server's own endpoint failed, not the release check: keep the last
      // notice and retry on the next tick.
    } finally {
      pending = false;
      if (!stopped && visibility.visibilityState === "visible") {
        timer = clock.setTimeout(
          () => void poll(),
          status === "unchecked" ? UPDATE_NOTICE_UNCHECKED_POLL_MS : UPDATE_NOTICE_POLL_MS,
        );
      }
    }
  };
  const changed = () => {
    clock.clearTimeout(timer);
    void poll();
  };
  visibility.addEventListener("visibilitychange", changed);
  void poll();
  return () => {
    stopped = true;
    clock.clearTimeout(timer);
    visibility.removeEventListener("visibilitychange", changed);
  };
}

export function useUpdateNotice(
  enabled: boolean,
  load = loadUpdateNotice,
  visibility: UpdateVisibility = document,
) {
  const [notice, setNotice] = useState<UpdateNotice | null>(null);
  useEffect(() => {
    if (!enabled) {
      setNotice(null);
      return;
    }
    return startUpdateNoticePolling(load, setNotice, visibility, window);
  }, [enabled, load, visibility]);
  return notice;
}
