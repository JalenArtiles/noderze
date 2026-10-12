"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ExternalLink, Globe, MapPin, Sparkles, Sun } from "lucide-react";
import { Callout, Empty, Err, Facts, JobList, Loading, Menu, PageHeader, RunButton, SectionHead, Tabs, useTab } from "@/components/ui";
import { useActivity } from "@/components/activity";
import { api, label, useApi } from "@/lib/api";
import { CompanyLogo } from "@/components/visual";

const ENTRY = ["entry_sales", "other_sales", "program"];

export default function CompanyPage() {
  const { id } = useParams() as { id: string };
  const { data, error, reload } = useApi(`/api/companies/${id}`);
  const [rawTab, setTab] = useTab("roles");
  const tab = rawTab === "jobs" ? "roles" : rawTab;
  const act = useActivity();
  if (error) return <Err msg={error} />;
  if (!data) return <Loading />;
  const c = data.company;
  const se = (c.data || {}).se_team || {};
  const forYou = data.jobs.filter((j: any) => ENTRY.includes(j.category) && !j.flags?.includes("outside_area"));
  const other = data.jobs.filter((j: any) => !forYou.includes(j));
  const run = (kind: string, body: any) => act.start({ kind, body, label: c.name, onDone: reload });
  return (
    <>
      <PageHeader
        crumb={<Link href="/companies">Companies</Link>}
        title={<span className="ph-id"><CompanyLogo name={c.name} website={c.website} size="lg" /><span>{c.name}</span></span>}
        lede={c.summary || (c.subcategory ? `${label(c.category)}: ${c.subcategory}` : label(c.category))}
        actions={<>
          <RunButton kind="full_company_analysis" body={{ company_id: c.id }} label={c.name} className="btn primary" onDone={reload}><Sparkles />Analyze company</RunButton>
          <Menu>
            <button onClick={() => run("discover_jobs", { company_ids: [c.id] })}>Scan its job board<span className="d">Checks for new and closed roles</span></button>
            <button onClick={() => run("deep_research", { company_id: c.id })}>Research only<span className="d">Sourced facts from the web</span></button>
            <button onClick={() => run("find_recruiters", { company_id: c.id })}>Find recruiters and alumni<span className="d">Public profiles that mention {c.name}</span></button>
            {c.website && <a href={c.website} target="_blank" rel="noreferrer">Open their website</a>}
          </Menu>
        </>}>
        <div className="meta">
          {c.az_presence && <span className="tag good" title={c.az_presence}><Sun />Arizona</span>}
          {c.remote_policy && <span className="tag"><Globe />{label(c.remote_policy)}</span>}
          {c.hq && <span className="tag"><MapPin />HQ {c.hq}</span>}
          {c.public_sector && <span className="tag">Public sector</span>}
          <span className="tag" title="How much of what we know comes from sourced facts">Research: {data.confidence.overall}</span>
        </div>
      </PageHeader>

      {c.watch_note && <Callout>{c.watch_note}</Callout>}

      <div className="stats" style={{ marginTop: c.watch_note ? "1rem" : 0 }}>
        <a className="stat" href="#" onClick={(e) => { e.preventDefault(); setTab("roles"); }}><b className="num">{forYou.length}</b><span>Roles for you</span></a>
        <div className="stat" title={(se.sample || []).join("; ")}><b className="num">{se.open_se_roles ?? "?"}</b><span>Open SE roles {se.seen ? "on their board" : "(not scanned yet)"}</span></div>
        <a className="stat" href="#" onClick={(e) => { e.preventDefault(); setTab("programs"); }}><b className="num">{data.programs.length}</b><span>ASE or SE programs</span></a>
        <a className="stat" href="#" onClick={(e) => { e.preventDefault(); setTab("people"); }}><b className="num">{data.people.length}</b><span>People saved</span></a>
      </div>

      <Tabs value={tab} onChange={setTab} tabs={[
        ["roles", "Roles", data.jobs.length], ["overview", "What we know"], ["standout", "Stand out"], ["people", "People", data.people.length],
        ["paths", "Career paths", data.career_paths.length], ["programs", "Programs", data.programs.length], ["similar", "Similar"], ["settings", "Job board"]]} />

      {tab === "roles" && <div className="stack-lg">
        <div><SectionHead title="For you" count={forYou.length} aside={<span className="muted">Entry sales and programs in your area</span>} />
          <JobList jobs={forYou} showCompany={false} onChange={reload} empty={<Empty title="No entry roles near you right now">New postings are picked up on every scan. Its SE roles are listed below.</Empty>} /></div>
        {other.length > 0 && <div><SectionHead title="Other roles" count={other.length} aside={<span className="muted">SE roles to grow into, technical roles and long shots</span>} />
          <JobList jobs={other} page={8} showCompany={false} onChange={reload} /></div>}
      </div>}

      {tab === "overview" && <section className="panel"><Facts facts={data.facts} labels={data.field_labels}
        empty={<Empty title="No sourced facts yet" action={<RunButton kind="deep_research" body={{ company_id: c.id }} label={c.name} onDone={reload}>Research {c.name}</RunButton>}>Research pulls facts about the company and its programs from the web, each with its source.</Empty>} /></section>}

      {tab === "standout" && <div className="list">{data.standout.map((s: any, i: number) => (
        <div key={i} className="li" style={{ alignItems: "flex-start" }}><div className="grow"><div className="title">{s.action}</div><div className="sub">{s.why}</div></div>{s.effort && <span className="tag">{s.effort}</span>}</div>))}</div>}

      {tab === "programs" && (data.programs.length ? <div className="list">{data.programs.map((p: any) => (
        <Link key={p.id} href={`/programs/${p.id}`} className="li"><div className="grow"><div className="title">{p.name}</div><div className="sub">{p.summary}</div></div><span className={`tag ${p.status === "open" ? "good" : ""}`}>{label(p.status)}</span></Link>))}</div>
        : <div className="panel"><Empty title="No programs on record">Associate SE academies and rotational programs show up here when research finds them.</Empty></div>)}

      {tab === "paths" && <Paths data={data} reload={reload} />}
      {tab === "people" && <People data={data} reload={reload} />}
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
    <div className="split">
      <section className="panel">
        <h3>Paths employees took</h3>
        <p className="small muted" style={{ marginTop: ".3rem" }}>{s.profiles ? `${s.profiles} profiles: ${s.reached_se} reached SE, ${s.transitions} moved in from sales or technical entry roles${s.median_months_to_se != null ? `, after a median of ${s.median_months_to_se} months` : ""}.` : "None yet."} Two or more moves into SE make sales roles here a LIKELY path.</p>
        <div style={{ marginTop: ".8rem" }}>{data.career_paths.map((p: any) => (
          <div key={p.id} className="fact"><b>{p.label}</b>{p.asu && <span className="tag good" style={{ marginLeft: 6 }}>ASU</span>}
            <div className="small" style={{ marginTop: ".2rem" }}>{p.steps.map((st: any) => `${st.title}${st.company ? ` (${st.company})` : ""}`).join(", then ")}</div>
            <div className="small muted">{p.reaches_se ? `Reached SE${p.months_to_se != null ? ` after ${p.months_to_se} months` : ""}` : "Has not reached SE"}. Started in {label(p.entry_family).toLowerCase()}.</div></div>))}</div>
      </section>
      <section className="panel stack">
        <h3>Add a profile</h3>
        <p className="small muted">Paste the Experience section of a public profile. Copy it from LinkedIn yourself; Noderze never reads LinkedIn.</p>
        <input placeholder="Profile link (optional, kept as the source)" value={url} onChange={(e) => setUrl(e.target.value)} />
        <textarea placeholder={"Solutions Engineer\nJan 2024 - Present\nAccount Development Representative\nAug 2022 - Jan 2024"} value={text} onChange={(e) => setText(e.target.value)} />
        <Err msg={err} /><button className="btn dark" onClick={add} disabled={!text}>Add path</button>
      </section>
    </div>);
}

function People({ data, reload }: any) {
  async function patch(id: number, body: any) { await api(`/api/people/${id}`, { method: "PATCH", body }); reload(); }
  return (
    <div className="stack-lg">
      <div className="row">
        <RunButton kind="find_recruiters" body={{ company_id: data.company.id }} label={data.company.name} className="btn dark" onDone={reload}>Find recruiters and alumni</RunButton>
        <a className="btn" href={data.alumni_tool_url} target="_blank" rel="noreferrer"><ExternalLink />ASU alumni at {data.company.name} on LinkedIn</a>
      </div>
      {data.people.length ? <div className="list">{data.people.map((p: any) => (
        <div key={p.id} className="li" style={{ alignItems: "flex-start" }}>
          <div className="grow">
            <div className="title">{p.name} <span className="muted" style={{ fontWeight: 400 }}>{p.title}</span></div>
            <div className="sub">{p.reason}</div>
            <div className="meta"><span className="tag">{label(p.role_category)}</span>{p.is_asu_alum !== "unknown" && <span className="tag good">ASU: {p.is_asu_alum}</span>}
              {p.verified ? <span className="tag good">Checked by you</span> : <span className="tag warn">Not checked yet</span>}</div>
          </div>
          <div className="end">
            {p.linkedin_url && <a className="btn sm" href={p.linkedin_url} target="_blank" rel="noreferrer">Profile</a>}
            {!p.verified && <button className="btn sm" onClick={() => patch(p.id, { verified: true })}>Mark checked</button>}
            <Link className="btn sm dark" href={`/contacts?person=${p.id}`}>Draft message</Link>
          </div>
        </div>))}</div>
        : <div className="panel"><Empty title="No people saved yet">Find recruiters searches public profiles that mention {data.company.name}. Everyone starts unchecked until you open their profile and confirm.</Empty></div>}
    </div>);
}

function Similar({ id }: { id: number }) {
  const { data, error } = useApi(`/api/companies/${id}/similar`);
  if (error) return <Err msg={error} />;
  if (!data) return <Loading />;
  return (
    <div className="stack-lg">
      <div className="list">{data.known.map((k: any) => <Link key={k.id} href={`/companies/${k.id}`} className="li"><div className="grow"><div className="title">{k.name}</div><div className="sub">{k.why}</div></div></Link>)}</div>
      {data.suggestions?.length > 0 && <div><SectionHead title="New suggestions from the web" />
        <div className="list">{data.suggestions.map((s: any, i: number) => <div key={i} className="li"><div className="grow"><div className="title">{s.name}</div><div className="sub">{s.why}</div></div><a className="btn sm" href={s.source_url} target="_blank" rel="noreferrer">Source</a></div>)}</div></div>}
    </div>);
}

function Board({ c, reload }: any) {
  const [f, setF] = useState({ ats_type: c.ats_type || "", ats_token: c.ats_token || "", ats_host: c.ats_host || "", ats_site: c.ats_site || "" });
  const [saved, setSaved] = useState(false);
  async function save() { await api(`/api/companies/${c.id}`, { method: "PATCH", body: f }); setSaved(true); reload(); }
  return (
    <section className="panel stack">
      <h3>Where Noderze reads {c.name}'s job postings</h3>
      <p className="small muted">Leave it on Auto-detect for Greenhouse, Lever and Ashby. For other boards, copy the details from the company's careers page link. {c.ats_verified ? "This board was read successfully." : "Not read successfully yet."}</p>
      <div className="form">
        <label className="field">Board type<select value={f.ats_type} onChange={(e) => setF({ ...f, ats_type: e.target.value })}><option value="">Auto-detect</option>{["greenhouse", "lever", "ashby", "smartrecruiters", "workday", "amazon"].map((t) => <option key={t} value={t}>{label(t)}</option>)}</select></label>
        <label className="field">Board name<input placeholder="e.g. verkada" value={f.ats_token} onChange={(e) => setF({ ...f, ats_token: e.target.value })} /></label>
        <label className="field">Workday host<input placeholder="company.wd5.myworkdayjobs.com" value={f.ats_host} onChange={(e) => setF({ ...f, ats_host: e.target.value })} /></label>
        <label className="field">Workday site<input placeholder="External_Careers" value={f.ats_site} onChange={(e) => setF({ ...f, ats_site: e.target.value })} /></label>
      </div>
      <div className="row"><button className="btn dark" onClick={save}>Save board</button>{saved && <span className="small muted">Saved. The next scan uses it.</span>}</div>
    </section>);
}
