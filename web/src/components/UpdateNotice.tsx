import { CircleArrowUp, LoaderCircle, Copy, Check } from "lucide-react";
import { useState } from "react";
import type { DesktopUpdate, DesktopBuildIdentity } from "../desktopRuntime";
import type { UpdateNotice as NoticeData } from "../types";
import { releaseNotice, dismissRelease, isReleaseDismissed } from "../updateNotice";

export function UpdateNotice({
  notice,
  identity,
  desktop,
  ...updater
}: DesktopUpdateNoticeProps & {
  notice: NoticeData | null;
  identity: DesktopBuildIdentity | null;
  desktop: boolean;
}) {
  const [, rerender] = useState(0);
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState(false);
  const release = releaseNotice(notice, identity);
  if (desktop && (updater.update || updater.error)) return <DesktopUpdateNotice {...updater} />;
  if (
    (desktop && !identity && notice?.space !== "team") ||
    !release ||
    isReleaseDismissed(release.dismissKey)
  )
    return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(release.command!);
      setCopied(release.command);
      setCopyError(false);
    } catch {
      setCopyError(true);
    }
  };
  return (
    <div
      className="desktop-update-notice release-update-notice"
      role="status"
      data-kind={release.kind}
    >
      <CircleArrowUp size={15} />
      <strong>
        RCP v{release.release} is out.{" "}
        {release.kind === "team" ? "This team server runs" : "This app is"} v{release.current}.
      </strong>
      {release.command ? (
        <>
          <code>{release.command}</code>
          <button className="button secondary" type="button" onClick={() => void copy()}>
            {copied === release.command ? <Check size={13} /> : <Copy size={13} />} Copy command
          </button>
        </>
      ) : null}
      {release.download ? (
        <a className="button secondary" href={release.download} target="_blank" rel="noreferrer">
          Download v{release.release}
        </a>
      ) : release.kind === "prebuilt" ? (
        <span>App build not yet published</span>
      ) : null}
      {copyError ? <span role="alert">Could not copy command</span> : null}
      <button
        className="desktop-update-dismiss"
        type="button"
        onClick={() => {
          dismissRelease(release.dismissKey);
          rerender((value) => value + 1);
        }}
      >
        Later
      </button>
    </div>
  );
}

export function ReleaseCheckRow({
  notice,
  label = "Updates",
}: {
  notice: NoticeData | null;
  label?: string;
}) {
  return (
    <dl
      className="release-check-row server-commit-rail"
      data-status={notice?.status ?? "unchecked"}
    >
      <div className="server-commit-row">
        <dt>{label}</dt>
        <dd>{notice?.status.replaceAll("_", " ") ?? "unchecked"}</dd>
      </div>
      <div className="server-commit-row">
        <dt>Last check</dt>
        <dd>
          {notice?.checked_at ? (
            <time dateTime={notice.checked_at}>{new Date(notice.checked_at).toLocaleString()}</time>
          ) : (
            "Not recorded"
          )}
        </dd>
      </div>
    </dl>
  );
}

export interface DesktopUpdateNoticeProps {
  update: DesktopUpdate | null;
  activeWork: boolean;
  expanded: boolean;
  applying: boolean;
  error: string | null;
  onExpand: () => void;
  onApply: () => void;
  onDismiss: () => void;
}

function DesktopUpdateNotice({
  update,
  activeWork,
  expanded,
  applying,
  error,
  onExpand,
  onApply,
  onDismiss,
}: DesktopUpdateNoticeProps) {
  if (update && activeWork && !expanded && !error) {
    return (
      <button className="desktop-update-marker" type="button" onClick={onExpand}>
        <CircleArrowUp size={13} /> Update ready
      </button>
    );
  }
  return (
    <div
      className={`desktop-update-notice${error ? " error" : ""}`}
      role={error ? "alert" : "status"}
    >
      <CircleArrowUp size={15} />
      <strong>{error || `RCP ${update?.version || "update"} is ready`}</strong>
      {update && (
        <button className="button secondary" type="button" disabled={applying} onClick={onApply}>
          {applying ? <LoaderCircle className="spin" size={13} /> : null}
          {activeWork ? "Update now" : "Update"}
        </button>
      )}
      <button className="desktop-update-dismiss" type="button" onClick={onDismiss}>
        Later
      </button>
    </div>
  );
}
