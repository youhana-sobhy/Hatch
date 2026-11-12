import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorMessages } from "../api";
import { Card, Code, Empty, Errors, StatusBadge, Track, ago, label } from "../components";
import { useAsync, useLiveReload } from "../hooks";
import type { Me, OnboardingDetail, StageRun } from "../types";

type Tab = "pipeline" | "config" | "compliance" | "audit";

export function OnboardingView({ me }: { me: Me }) {
  const { id = "" } = useParams();
  const detail = useAsync(() => api.get(id), [id]);
  const [tab, setTab] = useState<Tab>("pipeline");
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  useLiveReload(() => void detail.reload(), (e) => e.onboarding_id === id);

  const ob = detail.data;
  if (detail.error) return <Errors messages={errorMessages(detail.error)} />;
  if (!ob) return null;

  async function act(action: string, body?: unknown) {
    setBusy(true); setErrors([]);
    try {
      const result = await api.action(id, action, body);
      setMessage(result.message);
      await detail.reload();
    } catch (e) { setErrors(errorMessages(e)); } finally { setBusy(false); }
  }

  async function openReport() {
    const html = await api.report(id);
    const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    window.open(url, "_blank", "noopener");
  }

  const canApprove = ob.allowed_actions.includes("approve") && ["approver", "admin"].includes(me.role);

  return (
    <>
      <header className="page-head">
        <div>
          <div className="crumbs"><Link to="/onboardings">Onboardings</Link> / {ob.id}</div>
          <h1>{ob.hostname} <StatusBadge status={ob.status} /></h1>
          <p className="muted">{ob.vendor} {ob.model} · {ob.role} · {ob.site} ({ob.region}) · <code>{ob.mgmt_ip}</code> · serial <code>{ob.serial}</code></p>
        </div>
        <div className="row">
          {canApprove && <button className="primary" disabled={busy} onClick={() => void act("approve", { comment: "Approved in Hatch UI" })}>Approve</button>}
          {ob.allowed_actions.includes("retry") && <button className="primary" disabled={busy} onClick={() => void act("retry")}>Retry from {ob.failed_stage}</button>}
          {ob.allowed_actions.includes("rollback") && <button className="secondary" disabled={busy} onClick={() => void act("rollback")}>{ob.mode === "ztp" ? "Reset to Day-0" : "Roll back"}</button>}
          {ob.allowed_actions.includes("cancel") && <button className="ghost danger" disabled={busy} onClick={() => { if (confirm("Cancel this onboarding?")) void act("cancel", { reason: "cancelled in UI" }); }}>Cancel</button>}
          <button className="ghost" onClick={() => void openReport()}>Report</button>
        </div>
      </header>

      <Card><Track ob={ob} /></Card>
      {message && <div className="alert info">{message}</div>}
      <Errors messages={errors} />
      {ob.status === "FAILED" && (
        <div className="alert bad"><strong>Stopped at {ob.failed_stage}.</strong> {ob.error}</div>
      )}
      {ob.status === "PENDING_APPROVAL" && !canApprove && (
        <div className="alert warn">Waiting for an approver. Policy requires a second engineer for {ob.role} devices.</div>
      )}
      {ob.status === "WAITING_FOR_DEVICE" && (
        <div className="alert info">Waiting for the device to power on. It will fetch its Day-0 bootstrap from the ZTP service and call home with serial <code>{ob.serial}</code>.</div>
      )}

      <div className="grid-side">
        <div>
          <div className="tabs">
            {(["pipeline", "config", "compliance", "audit"] as Tab[]).map((t) => (
              <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{label(t)}</button>
            ))}
          </div>
          {tab === "pipeline" && <Pipeline stages={ob.stages} />}
          {tab === "config" && <ConfigTab id={id} />}
          {tab === "compliance" && <Compliance ob={ob} />}
          {tab === "audit" && <Audit id={id} status={ob.status} />}
        </div>
        <Card title="Details">
          <dl className="facts">
            <dt>Mode</dt><dd>{ob.mode === "ztp" ? "Zero-touch" : "Push"}</dd>
            <dt>Template</dt><dd>{ob.template_key}<br /><code>{ob.template_version}</code></dd>
            <dt>Config SHA-256</dt><dd><code>{ob.rendered_sha256?.slice(0, 16) ?? "—"}</code></dd>
            <dt>Requested by</dt><dd>{ob.requested_by}</dd>
            <dt>Approved by</dt><dd>{ob.approved_by ?? "—"}</dd>
            <dt>Ticket</dt><dd>{ob.ticket_ref ?? "—"}</dd>
            <dt>Attempt</dt><dd>{ob.attempt}</dd>
            <dt>Created</dt><dd>{new Date(ob.created_at).toLocaleString()}</dd>
            <dt>Completed</dt><dd>{ob.completed_at ? new Date(ob.completed_at).toLocaleString() : "—"}</dd>
            {ob.batch_id && <><dt>Batch</dt><dd><Link to={`/onboardings?batch_id=${ob.batch_id}`}>{ob.batch_id}</Link></dd></>}
          </dl>
        </Card>
      </div>
    </>
  );
}

function Pipeline({ stages }: { stages: StageRun[] }) {
  if (!stages.length) return <Card><Empty>No stage has run yet.</Empty></Card>;
  return (
    <Card>
      <ol className="stages">
        {stages.map((s, i) => {
          const checks = (s.details.checks as { name: string; passed: boolean; detail: string }[] | undefined) ?? [];
          const seconds = s.finished_at ? (new Date(s.finished_at).getTime() - new Date(s.started_at).getTime()) / 1000 : null;
          return (
            <li key={i} className={`stage ${s.status}`}>
              <div className="stage-head">
                <span className="stage-dot" />
                <code>{s.stage}</code>
                {s.attempt > 1 && <span className="tag">attempt {s.attempt}</span>}
                <span className="muted small">{s.status}{seconds != null && ` · ${seconds.toFixed(2)}s`} · {s.job_ref}</span>
              </div>
              <div className="stage-out">{s.output}</div>
              {checks.length > 0 && (
                <ul className="checks">
                  {checks.map((c) => <li key={c.name} className={c.passed ? "pass" : "fail"}><code>{c.name}</code> {c.detail}</li>)}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function ConfigTab({ id }: { id: string }) {
  const preview = useAsync(() => api.preview(id), [id]);
  const [view, setView] = useState<"config" | "diff">("config");
  if (preview.error) return <Errors messages={errorMessages(preview.error)} />;
  const p = preview.data;
  return (
    <Card
      title={p ? `${p.template} ${p.template_version}` : "Rendered configuration"}
      actions={
        <div className="seg">
          <button className={view === "config" ? "active" : ""} onClick={() => setView("config")}>Golden config</button>
          <button className={view === "diff" ? "active" : ""} onClick={() => setView("diff")}>Diff</button>
        </div>
      }
    >
      {p && (
        <>
          <p className="muted small">Layers {p.layers.join(" → ")}. Secrets are shown as placeholders and resolved only inside the pipeline. {view === "diff" && <>Compared against {p.diff_against}.</>}</p>
          <Code text={view === "config" ? p.config : p.diff || "(no differences)"} diff={view === "diff"} />
        </>
      )}
    </Card>
  );
}

function Compliance({ ob }: { ob: OnboardingDetail }) {
  const rules = ob.compliance.filter((c) => c.attempt === ob.attempt).length
    ? ob.compliance.filter((c) => c.attempt === ob.attempt)
    : ob.compliance;
  if (!rules.length) return <Card><Empty>The compliance scan has not run yet.</Empty></Card>;
  const passed = rules.filter((r) => r.passed).length;
  return (
    <Card title={`Security baseline · ${passed}/${rules.length} passed`}>
      <table className="table">
        <thead><tr><th>Rule</th><th>Severity</th><th>Result</th><th>Evidence</th></tr></thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.rule_id}>
              <td><code>{r.rule_id}</code><div>{r.title}</div></td>
              <td><span className={`sev sev-${r.severity}`}>{r.severity}</span></td>
              <td className={r.passed ? "ok-text" : "bad-text"}>{r.passed ? "pass" : "fail"}</td>
              <td className="evidence">{r.evidence}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Audit({ id, status }: { id: string; status: string }) {
  const audit = useAsync(() => api.audit({ onboarding_id: id }), [id, status]);
  return (
    <Card>
      <table className="table">
        <thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead>
        <tbody>
          {audit.data?.map((e) => (
            <tr key={e.id}>
              <td className="muted" title={e.at}>{ago(e.at)}</td>
              <td>{e.actor}</td>
              <td>
                {e.action === "transition" ? <>{e.from_status ? label(e.from_status) : "—"} → <strong>{label(e.to_status ?? "")}</strong></> : e.action}
                {typeof e.detail.reason === "string" && <div className="muted small">{e.detail.reason}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
