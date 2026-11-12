import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, StatusBadge, ago, label } from "../components";
import { useAsync, useLiveReload } from "../hooks";

const STATES = ["PENDING_APPROVAL", "WAITING_FOR_DEVICE", "DAY1_CONFIGURING", "VERIFYING", "COMPLIANCE_CHECK", "REGISTERING", "COMPLETED", "FAILED", "ROLLED_BACK", "CANCELLED"];

export function OnboardingList() {
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(params.entries());
  const list = useAsync(() => api.list({ limit: "200", ...filters }), [params.toString()]);
  const catalog = useAsync(api.catalog);
  useLiveReload(() => void list.reload(), (e) => e.type === "onboarding.status");

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Onboardings</h1>
          <p className="muted">{list.data?.total ?? 0} matching</p>
        </div>
        <Link className="button primary" to="/onboardings/new">New onboarding</Link>
      </header>
      <Card>
        <div className="filters">
          <input placeholder="Search hostname, serial or IP" value={filters.q ?? ""} onChange={(e) => set("q", e.target.value)} />
          <select value={filters.status ?? ""} onChange={(e) => set("status", e.target.value)}>
            <option value="">All statuses</option>
            {STATES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
          <select value={filters.site ?? ""} onChange={(e) => set("site", e.target.value)}>
            <option value="">All sites</option>
            {catalog.data?.sites.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
          <select value={filters.vendor ?? ""} onChange={(e) => set("vendor", e.target.value)}>
            <option value="">All vendors</option>
            {[...new Set(catalog.data?.models.map((m) => m.vendor))].map((v) => <option key={v}>{v}</option>)}
          </select>
          <select value={filters.mode ?? ""} onChange={(e) => set("mode", e.target.value)}>
            <option value="">Any mode</option>
            <option value="ztp">ZTP</option>
            <option value="push">Push</option>
          </select>
        </div>
        <table className="table">
          <thead>
            <tr><th>Device</th><th>Serial</th><th>Site</th><th>Mgmt IP</th><th>Template</th><th>Mode</th><th>Status</th><th>Requested</th></tr>
          </thead>
          <tbody>
            {list.data?.items.map((ob) => (
              <tr key={ob.id}>
                <td><Link to={`/onboardings/${ob.id}`}><strong>{ob.hostname}</strong></Link><div className="muted small">{ob.vendor} · {ob.model}</div></td>
                <td><code>{ob.serial}</code></td>
                <td>{ob.site}<div className="muted small">{ob.market}</div></td>
                <td><code>{ob.mgmt_ip}</code></td>
                <td>{ob.template_key}<div className="muted small">{ob.template_version}</div></td>
                <td><span className="tag">{ob.mode.toUpperCase()}</span></td>
                <td><StatusBadge status={ob.status} />{ob.failed_stage && <div className="muted small">at {ob.failed_stage}</div>}</td>
                <td className="muted">{ago(ob.created_at)}<div className="small">{ob.requested_by}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data?.items.length === 0 && <Empty>No onboardings match these filters.</Empty>}
      </Card>
    </>
  );
}
