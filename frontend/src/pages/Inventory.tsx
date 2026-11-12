import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty } from "../components";
import { useAsync, useLiveReload } from "../hooks";

export function Inventory() {
  const devices = useAsync(api.devices);
  useLiveReload(() => void devices.reload(), (e) => e.type === "onboarding.status");
  return (
    <>
      <header className="page-head">
        <div>
          <h1>Inventory</h1>
          <p className="muted">Hatch's source of truth. Devices are planned at registration and become active once onboarded.</p>
        </div>
      </header>
      <Card>
        <table className="table">
          <thead><tr><th>Hostname</th><th>Serial</th><th>Mgmt IP</th><th>Model</th><th>Site</th><th>Status</th><th>Monitored</th></tr></thead>
          <tbody>
            {devices.data?.map((d) => (
              <tr key={d.id}>
                <td>{d.onboarding_id ? <Link to={`/onboardings/${d.onboarding_id}`}>{d.hostname}</Link> : d.hostname}<div className="muted small">{d.role}</div></td>
                <td><code>{d.serial}</code></td>
                <td><code>{d.mgmt_ip}</code></td>
                <td>{d.vendor} · {d.model}</td>
                <td>{d.site}</td>
                <td><span className={`badge tone-${d.status === "active" ? "ok" : "info"}`}>{d.status}</span></td>
                <td>{d.monitored ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {devices.data?.length === 0 && <Empty>No devices yet.</Empty>}
      </Card>
    </>
  );
}
