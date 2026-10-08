"use client";
import Link from "next/link";
import { useState } from "react";
import { Globe, MapPin, Search, ShieldCheck, Sun, UserSearch } from "lucide-react";
import { Err } from "@/components/ui";
import { CompanyLogo } from "@/components/visual";
import { api, useApi } from "@/lib/api";

const WATCH: [string, string][] = [["priority", "Priority"], ["strong", "Strong target"], ["monitor", "Monitor"], ["edge", "Edge case"], ["not_relevant", "Not relevant"]];

export default function Companies() {
  const [cyber, setCyber] = useState(true);
  const [f, setF] = useState({ roles: false, se: false, q: "" });
  const { data, error, reload } = useApi<any[]>(`/api/company-board?cyber=${cyber}`);
  const [name, setName] = useState(""); const [err, setErr] = useState<string | null>(null);
  const list = (data || []).filter((c) => (!f.roles || c.entry_count > 0) && (!f.se || c.se_team.known) &&
    (!f.q || `${c.name} ${c.subcategory || ""}`.toLowerCase().includes(f.q.toLowerCase())));
  async function setStatus(id: number, v: string) { await api(`/api/companies/${id}`, { method: "PATCH", body: { watch_status: v || null } }); reload(); }
  async function add() { try { await api("/api/companies", { body: { name, category: cyber ? "cybersecurity" : null } }); setName(""); reload(); } catch (e: any) { setErr(e.message); } }
  return (
    <>
      <h1>Companies</h1>
      <p className="muted">Cybersecurity companies ranked for you: entry sales roles in Arizona, remote or Southern California, and a real SE team to grow into. Click Apply on any role.</p>
      <div className="filters">
        <div className="row"><span className="lab">Show</span><div className="chips">
          <button className={`chip ${cyber ? "on" : ""}`} onClick={() => setCyber(true)}><ShieldCheck />Cybersecurity</button>
          <button className={`chip ${!cyber ? "on" : ""}`} onClick={() => setCyber(false)}>All watched companies</button>
          <button className={`chip ${f.roles ? "on" : ""}`} onClick={() => setF({ ...f, roles: !f.roles })}>Has entry roles near me</button>
          <button className={`chip ${f.se ? "on" : ""}`} onClick={() => setF({ ...f, se: !f.se })}>Has an SE team</button></div></div>
        <div className="row"><span className="lab">Search</span><span className="row" style={{ gap: ".3rem" }}><Search size={16} className="muted" />
          <input placeholder="Company or product area" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} style={{ minWidth: 260 }} /></span></div>
      </div>
      <Err msg={error || err} />
      <p className="small muted">{data ? `${list.length} companies, best fit first. Companies without roles yet are still scanned every three hours.` : "Loading..."}</p>
      <div className="board">
        {list.map((c) => (
          <article key={c.id} className={`card co ${c.entry_count ? "entry_sales" : ""}`}>
            <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
              <CompanyLogo name={c.name} website={c.website} />
              <div style={{ flex: 1, minWidth: 0 }}><Link href={`/companies/${c.id}`} style={{ color: "var(--ink)" }}><b style={{ fontSize: "1.05rem" }}>{c.name}</b></Link>
                <div className="small muted">{c.subcategory || "Cybersecurity"}</div></div>
              <select value={c.watch_status || ""} onChange={(e) => setStatus(c.id, e.target.value)} aria-label={`Watch status for ${c.name}`} style={{ fontSize: ".78rem", padding: ".15rem .3rem" }}>
                {WATCH.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            </div>
            <div className="row small">
              {c.presence.az && <span className="badge good"><Sun size={12} />Arizona</span>}
              {c.presence.remote && <span className="badge good"><Globe size={12} />Remote</span>}
              {c.presence.socal && <span className="badge good"><MapPin size={12} />SoCal</span>}
              {c.se_team.known ? <span className="badge good" title={(c.se_team.sample || []).join("; ")}>{c.se_team.open_roles ? `SE team: ${c.se_team.open_roles} open SE roles` : "SE team confirmed"}</span>
                : <span className="badge">SE team not confirmed yet</span>}
              {c.programs > 0 && <span className="badge new">ASE or SE program</span>}
            </div>
            <div className="roles">
              {c.entry_roles.map((r: any) => (
                <Link key={r.id} href={`/apply/${r.id}`}><span>{r.title}{r.level ? <span className="muted"> · {r.level.split(" (")[0]}</span> : null}<span className="muted small"> {r.location}</span></span><b>{Math.round(r.score)}</b></Link>))}
              {!c.entry_roles.length && <div className="small muted">No entry sales roles in your area right now.</div>}
            </div>
            <div className="actions">
              {c.best ? <Link className="btn primary small" href={`/apply/${c.best.id}`}>Apply</Link> : <Link className="btn secondary small" href={`/companies/${c.id}?tab=jobs`}>All roles</Link>}
              <Link className="btn secondary small" href={c.best ? `/apply/${c.best.id}#recruiter` : `/companies/${c.id}?tab=people`}><UserSearch size={15} />Find recruiter</Link>
              <Link className="btn secondary small" href={`/companies/${c.id}`}>Company</Link>
            </div>
          </article>))}
      </div>
      <section className="panel row" style={{ marginTop: "1.4rem" }}>
        <b>Add a company</b><input placeholder="Company name" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn small" onClick={add} disabled={!name}>Add and watch</button>
        <span className="small muted">Its job board is found automatically on the next scan.</span>
      </section>
    </>
  );
}
