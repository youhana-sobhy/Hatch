import { useState, type ReactNode } from "react";
import type { Onboarding, Status } from "./types";

const TONE: Record<Status, string> = {
  REGISTERED: "neutral",
  VALIDATED: "neutral",
  PENDING_APPROVAL: "warn",
  APPROVED: "info",
  WAITING_FOR_DEVICE: "info",
  DAY0_APPLIED: "active",
  DAY1_CONFIGURING: "active",
  VERIFYING: "active",
  COMPLIANCE_CHECK: "active",
  REGISTERING: "active",
  COMPLETED: "ok",
  FAILED: "bad",
  ROLLED_BACK: "neutral",
  CANCELLED: "neutral",
};

export const label = (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`badge tone-${TONE[status] ?? "neutral"}`}>
      {TONE[status] === "active" && <span className="pulse" />}
      {label(status)}
    </span>
  );
}

const ZTP_TRACK: Status[] = [
  "VALIDATED", "APPROVED", "WAITING_FOR_DEVICE", "DAY0_APPLIED", "DAY1_CONFIGURING", "VERIFYING",
  "COMPLIANCE_CHECK", "REGISTERING", "COMPLETED",
];
const PUSH_TRACK: Status[] = [
  "VALIDATED", "APPROVED", "DAY1_CONFIGURING", "VERIFYING", "COMPLIANCE_CHECK", "REGISTERING", "COMPLETED",
];
const STAGE_OF: Record<string, Status> = {
  pre_validate: "DAY1_CONFIGURING", os_upgrade: "DAY1_CONFIGURING", render_config: "DAY1_CONFIGURING",
  push_config: "DAY1_CONFIGURING", post_checks: "VERIFYING", compliance_scan: "COMPLIANCE_CHECK",
  backup_config: "REGISTERING", register_device: "REGISTERING", report: "REGISTERING",
};
const SHORT: Partial<Record<Status, string>> = {
  VALIDATED: "Validated", APPROVED: "Approved", WAITING_FOR_DEVICE: "Discovered", DAY0_APPLIED: "Day-0",
  DAY1_CONFIGURING: "Day-1 config", VERIFYING: "Post-checks", COMPLIANCE_CHECK: "Compliance",
  REGISTERING: "Monitoring", COMPLETED: "Done",
};

/** The user-journey track: Discovered → Day-0 → Day-1 → Post-checks → Compliance → Monitoring → Done. */
export function Track({ ob }: { ob: Onboarding }) {
  const track = ob.mode === "ztp" ? ZTP_TRACK : PUSH_TRACK;
  const current: Status =
    ob.status === "FAILED" && ob.failed_stage
      ? STAGE_OF[ob.failed_stage]
      : ob.status === "PENDING_APPROVAL" || ob.status === "REGISTERED"
        ? "APPROVED"
        : ob.status;
  const index = track.indexOf(current);
  return (
    <ol className="track">
      {track.map((state, i) => {
        let cls = "todo";
        if (ob.status === "COMPLETED" || i < index) cls = "done";
        else if (i === index) cls = ob.status === "FAILED" ? "failed" : ob.status === "PENDING_APPROVAL" ? "waiting" : "current";
        if (ob.status === "CANCELLED" || ob.status === "ROLLED_BACK") cls = i < index ? "done" : "todo";
        return (
          <li key={state} className={cls}>
            <span className="dot" />
            <span className="track-label">{state === "APPROVED" && ob.status === "PENDING_APPROVAL" ? "Approval" : SHORT[state]}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function Code({ text, diff = false }: { text: string; diff?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="code-wrap">
      <button
        className="ghost small copy"
        onClick={() => {
          void navigator.clipboard?.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <pre className="code">
        {text.split("\n").map((line, i) => {
          let cls = "";
          if (diff) {
            if (line.startsWith("+") && !line.startsWith("+++")) cls = "add";
            else if (line.startsWith("-") && !line.startsWith("---")) cls = "del";
            else if (line.startsWith("@@")) cls = "hunk";
          }
          if (/\{\{ (device_)?secret:/.test(line)) cls += " secret";
          return (
            <span key={i} className={cls}>
              {line + "\n"}
            </span>
          );
        })}
      </pre>
    </div>
  );
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          <h3>{title}</h3>
          <div className="row">{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Errors({ messages }: { messages: string[] }) {
  if (!messages.length) return null;
  return (
    <div className="alert bad">
      {messages.map((m) => (
        <div key={m}>{m}</div>
      ))}
    </div>
  );
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

export const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
