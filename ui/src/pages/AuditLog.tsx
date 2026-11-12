import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, label } from "../components";
import { useAsync, useLiveReload } from "../hooks";

export function AuditLog() {
  const audit = useAsync(() => api.audit({ limit: "300" }));
  useLiveReload(() => void audit.reload());
  return (
    <>
      <header className="page-head">
        <div>
          <h1>Audit log</h1>
          <p className="muted">Append-only. Every request, approval, transition and stage failure, with who and when.</p>
        </div>
      </header>
      <Card>
        <table className="table">
          <thead><tr><th>Time (local)</th><th>Actor</th><th>Action</th><th>Onboarding</th><th>Change</th></tr></thead>
          <tbody>
            {audit.data?.map((e) => (
              <tr key={e.id}>
                <td className="muted">{new Date(e.at).toLocaleString()}</td>
                <td>{e.actor}</td>
                <td><code>{e.action}</code></td>
                <td>{e.onboarding_id && <Link to={`/onboardings/${e.onboarding_id}`}>{e.onboarding_id}</Link>}</td>
                <td>{e.to_status && <>{e.from_status ? label(e.from_status) : "—"} → {label(e.to_status)}</>}
                  {typeof e.detail.reason === "string" && <div className="muted small">{e.detail.reason}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
