"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Err, Facts, OpportunityCard, RunButton, Tabs, useTab } from "@/components/ui";
import { api, label, useApi } from "@/lib/api";
import { CompanyLogo } from "@/components/visual";

export default function CompanyPage() {
  const { id } = useParams() as { id: string };
  const { data, error, reload } = useApi(`/api/companies/${id}`);
  const [tab, setTab] = useTab("overview");
  if (error) return <Err msg={error} />;
  if (!data) return <p className="muted">Loading...</p>;
  const c = data.company;
  return (
    <>
      <div className="row" style={{ flexWrap: "nowrap" }}><CompanyLogo name={c.name} website={c.website} size="lg" /><h1 style={{ margin: 0 }}>{c.name}</h1></div>
      <p>{c.summary}</p>
      <div className="row small muted"><span>{label(c.category)}{c.subcategory ? `: ${c.subcategory}` : ""}</span>{c.hq && <span>HQ {c.hq}</span>}
        {c.az_presence && <span>Arizona: {c.az_presence}</span>}{c.ca_presence && <span>California: {c.ca_presence}</span>}
        {c.public_sector && <span className="badge">Public sector</span>}<span>Research confidence: <b>{data.confidence.overall}</b></span></div>
      {c.watch_note && <div className="notice" style={{ marginTop: ".6rem" }}>{c.watch_note}</div>}
      <div className="row" style={{ marginTop: ".9rem", alignItems: "flex-start" }}>
        <RunButton kind="full_company_analysis" body={{ company_id: c.id }} className="btn primary" onDone={reload}>Full company analysis</RunButton>
        <RunButton kind="deep_research" body={{ company_id: c.id }} className="btn secondary" onDone={reload}>Deep research only</RunButton>
        <RunButton kind="discover_jobs" body={{ company_ids: [c.id] }} className="btn secondary" onDone={reload}>Scan job board</RunButton>
      </div>
      <Tabs tabs={[["overview", "Overview"], ["jobs", `Roles (${data.jobs.length})`], ["programs", `Programs (${data.programs.length})`], ["paths", "Career paths"], ["people", "Recruiters and alumni"], ["standout", "Stand out"], ["similar", "Similar companies"], ["settings", "Job board"]]} value={tab} onChange={setTab} />
      {tab === "overview" && <section className="panel"><Facts facts={data.facts} labels={data.field_labels} /></section>}
      {tab === "jobs" && (data.jobs.length ? data.jobs.map((j: any) => <OpportunityCard key={j.id} job={j} onChange={reload} />) : <p className="muted">No roles stored. Scan the job board.</p>)}
      {tab === "programs" && data.programs.map((p: any) => (
        <article key={p.id} className="card program"><h3><Link href={`/programs/${p.id}`}>{p.name}</Link></h3><p className="small">{p.summary}</p>
          <Facts facts={p.facts} labels={data.field_labels} only={["program.duration", "program.location", "comp.base", "program.next_role"]} /></article>))}
      {tab === "paths" && <Paths data={data} reload={reload} />}
      {tab === "people" && <People data={data} reload={reload} />}
      {tab === "standout" && <section className="panel">{data.standout.map((s: any, i: number) => <div key={i} className="fact">{s.action}<div className="small muted">{s.why}{s.effort ? `. Effort: ${s.effort}` : ""}</div></div>)}</section>}
      {tab === "similar" && <Similar id={c.id} />}
      {tab === "settings" && <Board c={c} reload={reload} />}
    </>
  );
}

function Paths({ data, reload }: any) {
  const [text, setText] = useState(""); const [url, setUrl] = useState(""); const [err, setErr] = useState<string | null>(null);
  const s = data.path_summary;
  async function add() { try { await api("/api/career-paths/import", { body: { company_id: data.company.id, text, url: url || null } }); setText(""); setUrl(""); reload(); } catch (e: any) { setErr(e.message); } }
  return (
    <div className="grid2">
      <section className="panel"><h3>Observed paths</h3>
        <p className="small">{s.profiles} profiles, {s.reached_se} reached SE, {s.transitions} moved in from sales or technical entry roles{s.median_months_to_se != null ? `, median ${s.median_months_to_se} months` : ""}. Two or more transitions make sales roles here a LIKELY path.</p>
        {data.career_paths.map((p: any) => (
          <div key={p.id} className="fact"><b>{p.label}</b>{p.asu && <span className="badge good" style={{ marginLeft: 6 }}>ASU</span>}
            <div className="small">{p.steps.map((st: any) => `${st.title}${st.company ? ` (${st.company})` : ""}`).join("  >  ")}</div>
            <div className="small muted">{p.reaches_se ? `Reached SE${p.months_to_se != null ? ` after ${p.months_to_se} months` : ""}` : "Has not reached SE"}, entry: {label(p.entry_family)}</div></div>))}
      </section>
      <section className="panel stack"><h3>Add a profile</h3>
        <p className="small muted">Paste the Experience section of a public profile (copy it from LinkedIn yourself; the app never scrapes LinkedIn). The engine extracts the role sequence and checks for moves into SE.</p>
        <input placeholder="Profile URL (optional, kept as the source)" value={url} onChange={(e) => setUrl(e.target.value)} />
        <textarea placeholder={"Solutions Engineer\nJan 2024 - Present\nAccount Development Representative\nAug 2022 - Jan 2024"} value={text} onChange={(e) => setText(e.target.value)} />
        <Err msg={err} /><button className="btn" onClick={add} disabled={!text}>Extract path</button>
      </section>
    </div>);
}

function People({ data, reload }: any) {
  async function patch(id: number, body: any) { await api(`/api/people/${id}`, { method: "PATCH", body }); reload(); }
  return (
    <section className="stack">
      <div className="row"><RunButton kind="find_recruiters" body={{ company_id: data.company.id }} onDone={reload}>Find recruiters, SEs and ASU alumni</RunButton>
        <a className="btn secondary" href={data.alumni_tool_url} target="_blank" rel="noreferrer">Open LinkedIn's ASU alumni tool for {data.company.name}</a></div>
      <p className="small muted">People come only from public search results that mention {data.company.name}. Every entry starts unverified: open the profile and confirm before reaching out.</p>
      {data.people.map((p: any) => (
        <div key={p.id} className="card"><div className="spread"><div>
          <b>{p.name}</b> <span className="small muted">{p.title}</span>
          <div className="row small"><span className="badge">{label(p.role_category)}</span>{p.is_asu_alum !== "unknown" && <span className="badge good">ASU: {p.is_asu_alum}</span>}
            {p.verified ? <span className="badge good">Verified by you</span> : <span className="badge warn">Unverified</span>}</div>
          <div className="small" style={{ marginTop: ".3rem" }}>Contact this person because: {p.reason}</div></div>
          <div className="row">{p.linkedin_url && <a className="btn secondary small" href={p.linkedin_url} target="_blank" rel="noreferrer">Profile</a>}
            {!p.verified && <button className="btn small" onClick={() => patch(p.id, { verified: true })}>Mark verified</button>}
            <Link className="btn secondary small" href={`/contacts?person=${p.id}`}>Draft message</Link></div></div></div>))}
      {!data.people.length && <p className="muted">No people saved yet.</p>}
    </section>);
}

function Similar({ id }: { id: number }) {
  const { data, error } = useApi(`/api/companies/${id}/similar`);
  return (<section className="panel"><Err msg={error} />{!data && <p className="muted small">Loading...</p>}
    {data?.known.map((k: any) => <div key={k.id} className="fact"><Link href={`/companies/${k.id}`}>{k.name}</Link> <span className="small muted">{k.why}</span></div>)}
    {data?.suggestions?.length > 0 && <><h3 style={{ marginTop: "1rem" }}>New suggestions from the web</h3>{data.suggestions.map((s: any, i: number) => <div key={i} className="fact">{s.name}: <span className="small">{s.why}</span> <a className="small" href={s.source_url} target="_blank" rel="noreferrer">source</a></div>)}</>}
  </section>);
}

function Board({ c, reload }: any) {
  const [f, setF] = useState({ ats_type: c.ats_type || "", ats_token: c.ats_token || "", ats_host: c.ats_host || "", ats_site: c.ats_site || "" });
  async function save() { await api(`/api/companies/${c.id}`, { method: "PATCH", body: f }); reload(); }
  return (<section className="panel stack"><p className="small">Where the agent reads this company's own postings. Leave blank to auto-detect Greenhouse, Lever or Ashby. {c.ats_verified ? "Verified working." : "Not yet verified."}</p>
    <div className="row"><select value={f.ats_type} onChange={(e) => setF({ ...f, ats_type: e.target.value })}><option value="">Auto-detect</option>{["greenhouse", "lever", "ashby", "smartrecruiters", "workday", "amazon"].map((t) => <option key={t}>{t}</option>)}</select>
      <input placeholder="Board token (e.g. verkada)" value={f.ats_token} onChange={(e) => setF({ ...f, ats_token: e.target.value })} />
      <input placeholder="Workday host" value={f.ats_host} onChange={(e) => setF({ ...f, ats_host: e.target.value })} />
      <input placeholder="Workday site" value={f.ats_site} onChange={(e) => setF({ ...f, ats_site: e.target.value })} />
      <button className="btn" onClick={save}>Save</button></div></section>);
}
