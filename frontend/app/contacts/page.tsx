"use client";
import { useEffect, useState } from "react";
import { Err } from "@/components/ui";
import { api, day, label, useApi } from "@/lib/api";

const KINDS: [string, string][] = [["recruiter_connect", "Recruiter connection note"], ["recruiter_followup", "Recruiter follow-up"], ["employee_info", "Informational interview"], ["alumni", "ASU alumni note"], ["hiring_manager", "Hiring manager note"]];

export default function Contacts() {
  const people = useApi<any[]>("/api/people");
  const outreach = useApi<any[]>("/api/outreach");
  const companies = useApi<any[]>("/api/companies");
  const [sel, setSel] = useState<number | null>(null); const [kind, setKind] = useState("recruiter_connect");
  const [err, setErr] = useState<string | null>(null);
  const [f, setF] = useState<any>({ company_id: "", name: "", title: "", linkedin_url: "", role_category: "campus_recruiter" });
  useEffect(() => { const p = new URLSearchParams(window.location.search).get("person"); if (p) setSel(+p); }, []);
  async function draft() { try { await api("/api/outreach/generate", { body: { person_id: sel, kind } }); setErr(null); outreach.reload(); } catch (e: any) { setErr(e.message); } }
  async function add() { try { await api("/api/people", { body: { ...f, company_id: +f.company_id } }); people.reload(); } catch (e: any) { setErr(e.message); } }
  const [imp, setImp] = useState<string | null>(null);
  async function importCsv(file: File) {
    const form = new FormData(); form.append("file", file);
    try { const r = await api("/api/linkedin/connections", { form }); setImp(`Read ${r.connections} connections; ${r.at_tracked_companies} work at companies you're tracking. They now appear first on each Apply page.`); people.reload(); }
    catch (e: any) { setErr(e.message); }
  }
  return (
    <>
      <h1>Contacts and outreach</h1>
      <p className="muted">Recruiters, SEs and ASU alumni, with the reason each is worth contacting. The tracker blocks a second first-message to someone you already contacted.</p>
      <Err msg={err || people.error} />
      <section className="panel stack" style={{ marginBottom: "1rem" }}>
        <h3>Import your LinkedIn connections</h3>
        <p className="small">See who you already know at the companies you're targeting, so you can send warm messages instead of cold ones. On LinkedIn, click <b>Me</b>, then <b>Settings & Privacy</b>, then <b>Data privacy</b>, then <b>Get a copy of your data</b>. Choose <b>Connections</b> and request the archive. LinkedIn emails a download link, usually within about 10 minutes. Unzip it and upload <b>Connections.csv</b> here. Email addresses in the file are ignored.</p>
        <div className="row"><label className="btn">Upload Connections.csv<input type="file" accept=".csv" hidden onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} /></label>{imp && <span className="small">{imp}</span>}</div>
      </section>
      <div className="grid2">
        <section className="panel stack"><h3>Draft a message</h3>
          <select value={sel ?? ""} onChange={(e) => setSel(+e.target.value)}><option value="">Choose a person</option>{people.data?.map((p) => <option key={p.id} value={p.id}>{p.name}, {p.company} ({label(p.role_category)})</option>)}</select>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <button className="btn" onClick={draft} disabled={!sel}>Draft</button></section>
        <section className="panel stack"><h3>Add someone you know</h3><p className="small muted">For example, a recruiter you met at a career fair or someone your professor introduces.</p>
          <select value={f.company_id} onChange={(e) => setF({ ...f, company_id: e.target.value })}><option value="">Company</option>{companies.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <input placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /><input placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          <input placeholder="LinkedIn URL" value={f.linkedin_url} onChange={(e) => setF({ ...f, linkedin_url: e.target.value })} />
          <select value={f.role_category} onChange={(e) => setF({ ...f, role_category: e.target.value })}>{["campus_recruiter", "se_recruiter", "talent_partner", "hiring_manager", "se", "asu_alum", "other"].map((k) => <option key={k} value={k}>{label(k)}</option>)}</select>
          <button className="btn secondary" onClick={add} disabled={!f.name || !f.company_id}>Save contact</button></section>
      </div>
      <h2>Outreach log</h2>
      <table><thead><tr><th>Person</th><th>Message</th><th>Status</th><th>Sent</th><th>Reply</th></tr></thead><tbody>
        {outreach.data?.map((o) => <tr key={o.id}><td><b>{o.person.name}</b><div className="small muted">{label(o.kind)}</div></td><td className="small" style={{ maxWidth: 420 }}>{o.message}</td>
          <td><span className="badge">{o.status}</span></td><td className="small">{day(o.sent_at)}</td><td className="small">{o.response}</td></tr>)}</tbody></table>
      <h2>People</h2>
      <table><tbody>{people.data?.map((p) => <tr key={p.id}><td><b>{p.name}</b><div className="small muted">{p.title}</div></td><td>{p.company}</td><td className="small">{p.reason}</td><td>{p.verified ? <span className="badge good">verified</span> : <span className="badge warn">unverified</span>}</td></tr>)}</tbody></table>
    </>
  );
}
