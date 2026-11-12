import { useState } from "react";
import { api } from "../api";
import { Card, Code, Empty } from "../components";
import { useAsync } from "../hooks";

export function Templates() {
  const templates = useAsync(api.templates);
  const [selected, setSelected] = useState<string | null>(null);
  const [day0, setDay0] = useState(false);
  const detail = useAsync(() => (selected ? api.template(selected) : Promise.resolve(null)), [selected]);

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Golden templates</h1>
          <p className="muted">Versioned per vendor × role, changed only through review. The version includes a content hash, so every edit has a new identity.</p>
        </div>
      </header>
      <div className="grid-side reverse">
        <Card>
          <table className="table selectable">
            <thead><tr><th>Template</th><th>Version</th><th>Owner</th><th>Status</th></tr></thead>
            <tbody>
              {templates.data?.map((t) => (
                <tr key={t.key} className={selected === t.key ? "selected" : ""} onClick={() => { setSelected(t.key); setDay0(false); }}>
                  <td><strong>{t.key}</strong><div className="muted small">{t.description}</div></td>
                  <td><code>{t.full_version}</code></td>
                  <td>{t.owner}</td>
                  <td><span className={`badge tone-${t.status === "approved" ? "ok" : "warn"}`}>{t.status}</span>{t.has_day0 && <span className="tag">ZTP</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card
          title={detail.data ? detail.data.key : "Source"}
          actions={detail.data?.day0_source && (
            <div className="seg">
              <button className={!day0 ? "active" : ""} onClick={() => setDay0(false)}>Day-1 config.j2</button>
              <button className={day0 ? "active" : ""} onClick={() => setDay0(true)}>Day-0 day0.j2</button>
            </div>
          )}
        >
          {!detail.data ? <Empty>Select a template to read its source.</Empty> : (
            <>
              <p className="muted small">Required variables: {detail.data.required_vars.join(", ") || "none"}</p>
              <Code text={day0 ? detail.data.day0_source ?? "" : detail.data.source} />
            </>
          )}
        </Card>
      </div>
    </>
  );
}
