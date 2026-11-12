import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, StatusBadge, ago, duration, label, pct } from "../components";
import { useAsync, useEvents, useLiveReload } from "../hooks";
import type { HatchEvent, Status } from "../types";

export function Dashboard() {
  const stats = useAsync(api.stats);
  const recent = useAsync(() => api.list({ limit: "8" }));
  const [feed, setFeed] = useState<HatchEvent[]>([]);
  useLiveReload(() => { void stats.reload(); void recent.reload(); }, (e) => e.type === "onboarding.status");
  useEvents((e) => {
    if (e.type === "onboarding.status" || (e.type === "stage.finished" && e.status === "failed"))
      setFeed((f) => [e, ...f].slice(0, 12));
  });

  const s = stats.data;
  const total = s?.total ?? 0;
  const order: Status[] = ["PENDING_APPROVAL", "WAITING_FOR_DEVICE", "DAY1_CONFIGURING", "VERIFYING", "COMPLIANCE_CHECK", "HANDING_OVER", "FAILED", "COMPLETED"];

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">From racked and cabled to compliant and in monitoring, without the CLI.</p>
        </div>
        <Link className="button primary" to="/onboardings/new">New onboarding</Link>
      </header>

      <div className="kpis">
        <Kpi title="Onboardings" value={String(total)} hint={`${s?.in_flight ?? 0} in flight`} />
        <Kpi title="Median time to service" value={duration(s?.median_seconds_to_complete)} hint="request → completed" />
        <Kpi title="First-time right" value={pct(s?.first_time_right_rate)} hint="completed without retry" />
        <Kpi title="Day-1 compliance" value={pct(s?.compliance_pass_rate)} hint="baseline rules passed" />
        <Kpi title="Active devices" value={String(s?.active_devices ?? 0)} hint="in inventory + monitoring" />
      </div>

      <div className="grid-2">
        <Card title="Pipeline">
          {total === 0 ? <Empty>No onboardings yet.</Empty> : (
            <div className="bars">
              {order.map((state) => {
                const n = s?.by_status[state] ?? 0;
                return (
                  <Link key={state} to={`/onboardings?status=${state}`} className="bar-row">
                    <span>{label(state)}</span>
                    <span className="bar"><span className={`fill st-${state}`} style={{ width: `${total ? (n / total) * 100 : 0}%` }} /></span>
                    <span className="num">{n}</span>
                  </Link>
                );
              })}
            </div>
          )}
        </Card>
        <Card title="Live activity">
          {feed.length === 0 ? <Empty>Events appear here as devices move through Hatch.</Empty> : (
            <ul className="feed">
              {feed.map((e, i) => (
                <li key={i}>
                  <Link to={`/onboardings/${e.onboarding_id}`}>{e.hostname ?? e.onboarding_id}</Link>
                  {e.type === "onboarding.status" ? <> → <StatusBadge status={e.to as Status} /></> : <> failed <code>{e.stage}</code></>}
                  <small className="muted">{ago(e.at)}</small>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Recent onboardings" actions={<Link to="/onboardings">View all</Link>}>
        <table className="table">
          <thead><tr><th>Device</th><th>Site</th><th>Mode</th><th>Status</th><th>Updated</th></tr></thead>
          <tbody>
            {recent.data?.items.map((ob) => (
              <tr key={ob.id}>
                <td><Link to={`/onboardings/${ob.id}`}><strong>{ob.hostname}</strong></Link><div className="muted small">{ob.vendor} · {ob.model}</div></td>
                <td>{ob.site}</td>
                <td><span className="tag">{ob.mode.toUpperCase()}</span></td>
                <td><StatusBadge status={ob.status} /></td>
                <td className="muted">{ago(ob.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {recent.data?.items.length === 0 && <Empty>Nothing here yet. Start with a new onboarding.</Empty>}
      </Card>
    </>
  );
}

function Kpi({ title, value, hint }: { title: string; value: string; hint: string }) {
  return (
    <div className="kpi">
      <small>{title}</small>
      <strong>{value}</strong>
      <span className="muted">{hint}</span>
    </div>
  );
}
