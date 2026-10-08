"use client";
import { useEffect, useState } from "react";
import { Err } from "@/components/ui";
import { api, day, useApi } from "@/lib/api";

const LABELS: Record<string, string> = { career_path: "Career path", technical_fit: "Technical fit", geography: "Geography", development: "Development program",
  eligibility: "Eligibility and timing", sales_leverage: "Sales experience leverage", compensation: "Compensation", evidence: "Evidence strength" };

export default function Settings() {
  const { data, error, reload } = useApi("/api/profile");
  const rules = useApi<any[]>("/api/alert-rules");
  const [w, setW] = useState<Record<string, number>>({}); const [json, setJson] = useState(""); const [msg, setMsg] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (data) { setW(data.weights); setJson(JSON.stringify(data.data, null, 2)); } }, [data]);
  const total = Object.values(w).reduce((a, b) => a + Number(b), 0);
  async function save(body: any) { try { const r = await api("/api/profile", { method: "PUT", body }); setMsg(`Saved. Rescored ${r.rescored} jobs.`); setErr(null); reload(); } catch (e: any) { setErr(e.message); } }
  async function toggle(r: any) { await api(`/api/alert-rules/${r.id}`, { method: "PATCH", body: { enabled: !r.enabled } }); rules.reload(); }
  return (
    <>
      <h1>Settings</h1>
      <Err msg={error || err} />{msg && <div className="notice">{msg}</div>}
      <h2>Scoring weights</h2>
      <p className="small muted">Weights are normalized to 100, so only their relative size matters. Current total: {total}.</p>
      <div className="panel"><div className="bars" style={{ gridTemplateColumns: "190px 1fr 50px" }}>
        {Object.keys(LABELS).map((k) => (<div key={k} style={{ display: "contents" }}><label htmlFor={k}>{LABELS[k]}</label>
          <input id={k} type="range" min={0} max={40} value={w[k] ?? 0} onChange={(e) => setW({ ...w, [k]: +e.target.value })} /><span className="num">{w[k]}</span></div>))}
      </div><button className="btn" style={{ marginTop: ".7rem" }} onClick={() => save({ weights: w })}>Save weights and rescore</button></div>
      <h2>Profile</h2>
      <p className="small muted">The structured profile the agent reasons from. Fill <code>work_authorization</code> and <code>story_hook</code>; several programs do not sponsor visas, and interview answers open with your story.</p>
      <textarea value={json} onChange={(e) => setJson(e.target.value)} style={{ minHeight: 360, fontSize: ".85rem" }} />
      <button className="btn" onClick={() => { try { save({ data: JSON.parse(json) }); } catch { setErr("That is not valid JSON."); } }}>Save profile</button>
      <h2>Scheduled scans</h2>
      <table><thead><tr><th>Rule</th><th>Schedule (cron, America/Phoenix)</th><th>Last run</th><th></th></tr></thead><tbody>
        {rules.data?.map((r) => <tr key={r.id}><td>{r.name}</td><td><code>{r.cron}</code></td><td className="small">{day(r.last_run_at)}</td><td><button className="btn secondary small" onClick={() => toggle(r)}>{r.enabled ? "Pause" : "Resume"}</button></td></tr>)}</tbody></table>
    </>
  );
}
