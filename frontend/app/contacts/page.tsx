"use client";
import { useEffect, useState } from "react";
import { Upload } from "lucide-react";
import { Callout, Empty, Err, PageHeader, SectionHead } from "@/components/ui";
import { api, day, label, useApi } from "@/lib/api";

const KINDS: [string, string][] = [["recruiter_connect", "Recruiter connection note"], ["recruiter_followup", "Recruiter follow-up"], ["employee_info", "Informational interview"], ["alumni", "ASU alumni note"], ["hiring_manager", "Hiring manager note"]];

export default function Contacts() {
  const people = useApi<any[]>("/api/people");
  const outreach = useApi<any[]>("/api/outreach");
  const companies = useApi<any[]>("/api/companies");
  const [sel, setSel] = useState<number | null>(null); const [kind, setKind] = useState("recruiter_connect");
  const [err, setErr] = useState<string | null>(null);
  const [f, setF] = useState<any>({ company_id: "", name: "", title: "", linkedin_url: "", role_category: "campus_recruiter" });
  const [imp, setImp] = useState<string | null>(null);
  useEffect(() => { const p = new URLSearchParams(window.location.search).get("person"); if (p) setSel(+p); }, []);
  async function draft() { try { await api("/api/outreach/generate", { body: { person_id: sel, kind } }); setErr(null); outreach.reload(); } catch (e: any) { setErr(e.message); } }
  async function add() { try { await api("/api/people", { body: { ...f, company_id: +f.company_id } }); setF({ ...f, name: "", title: "", linkedin_url: "" }); people.reload(); } catch (e: any) { setErr(e.message); } }
  async function importCsv(file: File) {
    const form = new FormData(); form.append("file", file);
    try { const r = await api("/api/linkedin/connections", { form }); setImp(`Read ${r.connections} connections. ${r.at_tracked_companies} work at companies you're watching, and they now show first on each Apply page.`); people.reload(); }
    catch (e: any) { setErr(e.message); }
  }
  return (
    <>
      <PageHeader title="Contacts" lede="Recruiters, SEs and alumni worth reaching, with the reason for each. Noderze stops you from sending a second first message to the same person." />
      <Err msg={err || people.error} />
      <div className="grid2">
        <section className="panel stack">
          <h3>Import your LinkedIn connections</h3>
          <p className="small muted">See who you already know at the companies you're targeting, so your first message is warm instead of cold.</p>
          <ol className="small" style={{ margin: 0, paddingLeft: "1.1rem", lineHeight: 1.7 }}>
            <li>On LinkedIn, open <b>Me</b>, then <b>Settings & Privacy</b>, then <b>Data privacy</b>.</li>
            <li>Choose <b>Get a copy of your data</b>, pick <b>Connections</b>, and request it.</li>
            <li>LinkedIn emails a link, usually within about 10 minutes. Unzip it and upload <b>Connections.csv</b>.</li>
          </ol>
          <label className="btn dark" style={{ width: "fit-content" }}><Upload />Upload Connections.csv<input type="file" accept=".csv" hidden onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} /></label>
          {imp && <Callout>{imp}</Callout>}
        </section>
        <section className="panel stack">
          <h3>Add someone you know</h3>
          <p className="small muted">For example, a recruiter you met at a career fair or someone your professor introduces.</p>
          <div className="form">
            <label className="field">Company<select value={f.company_id} onChange={(e) => setF({ ...f, company_id: e.target.value })}><option value="">Choose</option>{companies.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
            <label className="field">Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
            <label className="field">Title<input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
            <label className="field">Role<select value={f.role_category} onChange={(e) => setF({ ...f, role_category: e.target.value })}>{["campus_recruiter", "se_recruiter", "talent_partner", "hiring_manager", "se", "asu_alum", "other"].map((k) => <option key={k} value={k}>{label(k)}</option>)}</select></label>
          </div>
          <label className="field">LinkedIn link<input value={f.linkedin_url} onChange={(e) => setF({ ...f, linkedin_url: e.target.value })} /></label>
          <button className="btn dark" style={{ width: "fit-content" }} onClick={add} disabled={!f.name || !f.company_id}>Save contact</button>
        </section>
      </div>

      <div className="sec">
        <SectionHead title="People" count={people.data?.length ?? null} />
        {people.data?.length ? <div className="list">{people.data.map((p) => (
          <div key={p.id} className="li" style={{ alignItems: "flex-start" }}>
            <div className="grow"><div className="title">{p.name} <span className="muted" style={{ fontWeight: 400 }}>{p.title}{p.company ? `, ${p.company}` : ""}</span></div><div className="sub">{p.reason}</div></div>
            <div className="end">{p.verified ? <span className="tag good">Checked</span> : <span className="tag warn">Not checked</span>}
              <button className={`btn sm ${sel === p.id ? "dark" : ""}`} onClick={() => setSel(p.id)}>{sel === p.id ? "Selected" : "Write to"}</button></div>
          </div>))}</div>
          : <div className="panel"><Empty title="No people yet">Add someone above, import your connections, or run Find recruiters on a company page.</Empty></div>}
        {sel && <div className="panel row" style={{ marginTop: ".8rem" }}>
          <span className="small">Draft for <b>{people.data?.find((p) => p.id === sel)?.name}</b></span>
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Message type">{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <button className="btn primary sm" onClick={draft}>Draft message</button></div>}
      </div>

      <div className="sec">
        <SectionHead title="Messages" count={outreach.data?.length ?? null} />
        {outreach.data?.length ? <div className="list">{outreach.data.map((o) => (
          <div key={o.id} className="li" style={{ alignItems: "flex-start" }}>
            <div className="grow"><div className="title">{o.person.name} <span className="muted" style={{ fontWeight: 400 }}>{label(o.kind)}</span></div>
              <div className="sub" style={{ whiteSpace: "pre-wrap" }}>{o.message}</div>{o.response && <div className="small" style={{ marginTop: ".3rem" }}>Reply: {o.response}</div>}</div>
            <div className="end"><span className="tag">{label(o.status)}</span>{o.sent_at && <span className="tiny muted">{day(o.sent_at)}</span>}</div>
          </div>))}</div>
          : <div className="panel"><Empty title="No messages yet">Drafts you make here or on an Apply page show up with their status.</Empty></div>}
      </div>
    </>
  );
}
