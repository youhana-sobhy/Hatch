import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessages } from "../api";
import { Card, Code, Errors, StatusBadge } from "../components";
import { useAsync } from "../hooks";
import type { BatchResult, DryRun } from "../types";

interface Uplink { interface: string; peer: string; peer_interface: string }

const EMPTY = { site: "", model: "", role: "", serial: "", hostname: "", mgmt_ip: "", mode: "push", ticket_ref: "" };

export function NewOnboarding() {
  const [tab, setTab] = useState<"single" | "bulk">("single");
  return (
    <>
      <header className="page-head">
        <div>
          <h1>New onboarding</h1>
          <p className="muted">Hatch validates everything and shows the rendered golden config before anything touches a device.</p>
        </div>
      </header>
      <div className="tabs">
        <button className={tab === "single" ? "active" : ""} onClick={() => setTab("single")}>Single device</button>
        <button className={tab === "bulk" ? "active" : ""} onClick={() => setTab("bulk")}>Bulk import (CSV)</button>
      </div>
      {tab === "single" ? <SingleForm /> : <BulkImport />}
    </>
  );
}

function SingleForm() {
  const navigate = useNavigate();
  const catalog = useAsync(api.catalog);
  const [form, setForm] = useState(EMPTY);
  const [uplinks, setUplinks] = useState<Uplink[]>([]);
  const [vars, setVars] = useState("{}");
  const [dry, setDry] = useState<DryRun | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"config" | "diff">("config");

  const model = catalog.data?.models.find((m) => m.name === form.model);
  const roles = model?.roles ?? [];
  const update = (patch: Partial<typeof EMPTY>) => { setForm((f) => ({ ...f, ...patch })); setDry(null); };

  const body = useMemo(() => {
    let parsed: Record<string, unknown> = {};
    try { parsed = JSON.parse(vars || "{}"); } catch { /* reported on submit */ }
    return {
      ...form,
      ticket_ref: form.ticket_ref || null,
      uplinks: uplinks.filter((u) => u.interface).map((u) => ({ interface: u.interface, peer: u.peer || null, peer_interface: u.peer_interface || null })),
      vars: parsed,
    };
  }, [form, uplinks, vars]);

  async function suggest() {
    if (!form.site || !form.role) return;
    const [pick] = await api.suggest(form.site, form.role);
    if (pick) update({ hostname: pick.hostname, mgmt_ip: pick.mgmt_ip });
  }

  async function validate() {
    try { JSON.parse(vars || "{}"); } catch { setErrors(["Device variables must be valid JSON"]); return; }
    setBusy(true);
    setErrors([]);
    try { setDry(await api.dryRun(body)); } catch (e) { setErrors(errorMessages(e)); } finally { setBusy(false); }
  }

  async function submit() {
    setBusy(true);
    try {
      const result = await api.create(body);
      navigate(`/onboardings/${result.created[0].id}`);
    } catch (e) { setErrors(errorMessages(e)); } finally { setBusy(false); }
  }

  return (
    <div className="grid-form">
      <Card title="Device">
        <div className="form">
          <label>Site
            <select value={form.site} onChange={(e) => update({ site: e.target.value })}>
              <option value="">Choose a site</option>
              {catalog.data?.sites.map((s) => <option key={s.name} value={s.name}>{s.name} · {s.description} ({s.region})</option>)}
            </select>
          </label>
          <label>Model
            <select value={form.model} onChange={(e) => {
              const m = catalog.data?.models.find((x) => x.name === e.target.value);
              update({ model: e.target.value, role: m?.roles[0] ?? "" });
            }}>
              <option value="">Choose a model</option>
              {catalog.data?.models.map((m) => <option key={m.name} value={m.name}>{m.vendor} · {m.name}</option>)}
            </select>
          </label>
          <label>Role
            <select value={form.role} onChange={(e) => update({ role: e.target.value })} disabled={!roles.length}>
              {roles.map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
          <label>Serial number
            <input value={form.serial} onChange={(e) => update({ serial: e.target.value.toUpperCase() })} placeholder="FDO2401A1BC" />
          </label>
          <div className="row-2">
            <label>Hostname
              <input value={form.hostname} onChange={(e) => update({ hostname: e.target.value })} placeholder="ams-dc1-leaf-01" />
            </label>
            <label>Management IP
              <input value={form.mgmt_ip} onChange={(e) => update({ mgmt_ip: e.target.value })} placeholder="10.201.10.21" />
            </label>
          </div>
          <button className="ghost small" onClick={() => void suggest()} disabled={!form.site || !form.role}>Suggest hostname and IP from IPAM</button>
          <div className="row-2">
            <label>Delivery
              <select value={form.mode} onChange={(e) => update({ mode: e.target.value })}>
                <option value="push">Push (device already reachable)</option>
                <option value="ztp">Zero-touch (ZTP)</option>
              </select>
            </label>
            <label>Ticket
              <input value={form.ticket_ref} onChange={(e) => update({ ticket_ref: e.target.value })} placeholder="CHG-12345" />
            </label>
          </div>
          <fieldset>
            <legend>Uplinks (cabling plan)</legend>
            {uplinks.map((u, i) => (
              <div className="row-3" key={i}>
                {(["interface", "peer", "peer_interface"] as const).map((k) => (
                  <input key={k} placeholder={k.replace("_", " ")} value={u[k]} onChange={(e) => {
                    const next = [...uplinks]; next[i] = { ...u, [k]: e.target.value }; setUplinks(next); setDry(null);
                  }} />
                ))}
              </div>
            ))}
            <button className="ghost small" onClick={() => setUplinks([...uplinks, { interface: "", peer: "", peer_interface: "" }])}>Add uplink</button>
          </fieldset>
          <label>Device variables (JSON, last template layer)
            <textarea rows={4} value={vars} onChange={(e) => { setVars(e.target.value); setDry(null); }} spellCheck={false} />
          </label>
          <Errors messages={errors} />
          <div className="row">
            <button className="secondary" onClick={() => void validate()} disabled={busy}>Validate and preview</button>
            <button className="primary" onClick={() => void submit()} disabled={busy || !dry?.valid}>Submit onboarding</button>
          </div>
        </div>
      </Card>

      <Card
        title="Validation and preview"
        actions={dry?.preview && (
          <div className="seg">
            <button className={view === "config" ? "active" : ""} onClick={() => setView("config")}>Rendered config</button>
            <button className={view === "diff" ? "active" : ""} onClick={() => setView("diff")}>Diff</button>
          </div>
        )}
      >
        {!dry && <div className="empty">Fill in the device and press <strong>Validate and preview</strong>.</div>}
        {dry && (
          <>
            {dry.valid ? (
              <div className="alert ok">
                All checks passed. {dry.requires_approval ? "This role needs an approver's sign-off before anything is pushed." : "Auto-approved by policy."}
              </div>
            ) : <Errors messages={dry.errors.map((e) => `${e.field}: ${e.message}`)} />}
            {dry.preview && (
              <>
                <p className="muted small">
                  {dry.preview.template} <code>{dry.preview.template_version}</code> · layers {dry.preview.layers.join(" → ")} · {dry.preview.secrets.length} secrets resolved at run time, never shown
                </p>
                <Code text={view === "config" ? dry.preview.config : dry.preview.diff || "(no differences)"} diff={view === "diff"} />
              </>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

const SAMPLE = `serial,model,role,site,mode,ticket_ref,hostname,mgmt_ip,uplinks
CZ2401AAAA,PowerEdge-R760,compute-host,ams-dc1,push,CHG-20600,,,vmnic0=ams-dc1-leaf-01:Ethernet1/5
CZ2401AAAB,PowerEdge-R760,compute-host,ams-dc1,push,CHG-20600,,,vmnic0=ams-dc1-leaf-01:Ethernet1/6
`;

function BulkImport() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function upload() {
    if (!file) return;
    setBusy(true); setErrors([]);
    try { setResult(await api.importCsv(file)); } catch (e) { setErrors(errorMessages(e)); } finally { setBusy(false); }
  }

  return (
    <div className="grid-2">
      <Card title="Upload">
        <p className="muted">One device per row. Leave <code>hostname</code> and <code>mgmt_ip</code> blank and Hatch allocates them from the site's naming pattern and IPAM. Uplinks use <code>if=peer:peer_if;…</code>.</p>
        <Code text={SAMPLE} />
        <div className="row">
          <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <button className="primary" disabled={!file || busy} onClick={() => void upload()}>Import</button>
        </div>
        <Errors messages={errors} />
      </Card>
      <Card title="Result">
        {!result && <div className="empty">Results appear here.</div>}
        {result && (
          <>
            <p><strong>{result.created.length}</strong> created, <strong>{result.rejected.length}</strong> rejected{result.batch_id && <> · batch <Link to={`/onboardings?batch_id=${result.batch_id}`}><code>{result.batch_id}</code></Link></>}</p>
            <table className="table">
              <tbody>
                {result.created.map((ob) => (
                  <tr key={ob.id}><td><Link to={`/onboardings/${ob.id}`}>{ob.hostname}</Link></td><td><code>{ob.mgmt_ip}</code></td><td><StatusBadge status={ob.status} /></td></tr>
                ))}
                {result.rejected.map((r) => (
                  <tr key={`r${r.index}`} className="rejected"><td>row {r.index} {r.hostname}</td><td colSpan={2}>{r.errors.map((e) => e.message).join("; ")}</td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>
    </div>
  );
}
