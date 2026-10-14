"use client";
import { useEffect, useMemo, useState } from "react";
import { BarChart3, CalendarRange, CircleDollarSign, Clock, ExternalLink, Globe, MapPin, Network, Search, Shield } from "lucide-react";
import { Empty, Err, Loading, Menu, PageHeader, RunButton, SectionHead, Tabs } from "@/components/ui";
import { InternRow, Season, TRACKS } from "@/components/intern";
import { api, useApi } from "@/lib/api";

const TRACK_ICON: Record<string, any> = { cyber: Shield, data: BarChart3, network: Network };
const WHERE: [string, string, any][] = [["", "Anywhere that works", null], ["remote", "Remote", Globe], ["phoenix", "Phoenix area", MapPin]];

const uniq = (list: any[]) => new Set(list.map((j) => `${j.company}|${j.title}`)).size;

function ago(iso?: string | null) {
  if (!iso) return null;
  const m = Math.round((Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 60000);
  return m < 2 ? "just now" : m < 60 ? `${m} minutes ago` : m < 48 * 60 ? `${Math.round(m / 60)} hours ago` : `${Math.round(m / 1440)} days ago`;
}

export default function Internships() {
  const { data, error, reload } = useApi<any>("/api/internships");
  const [tab, setTab] = useState("ok");
  const [track, setTrack] = useState("");
  const [where, setWhere] = useState("");
  const [q, setQ] = useState("");
  const [fresh, setFresh] = useState(false);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("tab") === "out") setTab("out");
    if (p.get("new") === "1") setFresh(true);
    if (p.get("track")) setTrack(p.get("track") || "");
  }, []);
  const items: any[] = data?.items || [];
  const filtered = useMemo(() => items.filter((j) => {
    const it = j.intern || {};
    if (track && it.track !== track) return false;
    if (where === "remote" && it.where?.status !== "remote") return false;
    if (where === "phoenix" && !["phoenix", "hybrid_phoenix"].includes(it.where?.status)) return false;
    if (fresh && !j.new) return false;
    if (q && !`${j.title} ${j.company} ${j.location_text || ""}`.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  }), [items, track, where, q, fresh]);
  const ok = filtered.filter((j) => j.intern?.status !== "out");
  const out = filtered.filter((j) => j.intern?.status === "out");
  const trackCount = (t: string) => items.filter((j) => j.intern?.status !== "out" && (!t || j.intern?.track === t)).length;
  const p = data?.prefs || { hours_min: 10, hours_max: 30 };
  // Big employers post the same internship once per team; show each one once, with a count.
  const grouped = useMemo(() => {
    const seen = new Map<string, any>();
    for (const j of tab === "out" ? out : ok) {
      const k = `${j.company}|${j.title}|${j.intern?.status}`;
      if (seen.has(k)) seen.get(k).count += 1; else seen.set(k, { job: j, count: 1 });
    }
    return Array.from(seen.values());
  }, [tab, out, ok]);
  const shown = tab === "out" ? out : ok;
  const neverScanned = data && !data.last_scan;
  return (
    <>
      <PageHeader title="Spring internships"
        lede={<>Paid, part-time data, cybersecurity and networking internships for January to May 2027, remote or in the Phoenix area. Each one is checked against your rules before it shows up here.</>}
        actions={<>
          <RunButton kind="find_internships" label="Spring internships" className="btn primary" onDone={() => reload()}><Search />Find internships</RunButton>
          <Menu>
            <a href="#add">Add one you found<span className="d">A link or the posting text</span></a>
            <a href="#sites">Search Handshake and LinkedIn<span className="d">Sites you log into yourself</span></a>
            {data?.has_hidden && <button onClick={async () => { await api("/api/internships/unhide", { body: {} }); reload(); }}>Show hidden internships</button>}
          </Menu>
        </>} />

      <div className="iseason panel">
        <Season />
        <div className="rules" aria-label="What qualifies">
          <span><Shield />Data, cybersecurity or networking</span>
          <span><CircleDollarSign />Paid, with some sign of pay</span>
          <span><Clock />{p.hours_min} to {p.hours_max} hours a week</span>
          <span><CalendarRange />January to May 2027</span>
          <span><MapPin />Remote, or onsite in the Phoenix area</span>
        </div>
        <p className="tiny faint">{data?.running ? "Searching now. New internships appear as they're found." : data?.last_scan ? `Last search ${ago(data.last_scan)}. Noderze searches again every morning.` : "Not searched yet."}</p>
      </div>

      <Err msg={error} />
      {!data ? <Loading what="Loading internships" /> : neverScanned && !items.length ? (
        <div className="panel"><Empty title="No search yet" action={<RunButton kind="find_internships" label="Spring internships" className="btn primary" onDone={() => reload()}>Find internships</RunButton>}>
          Noderze reads the public internship lists and the job boards of Phoenix-area employers, SRP, APS and the State of Arizona, then checks pay, hours, dates and location. It takes a few minutes.</Empty></div>
      ) : (
        <>
          <div className="toolbar" style={{ marginTop: "1.2rem" }}>
            <div className="chips">
              <button className={`chip ${!track ? "on" : ""}`} onClick={() => setTrack("")}>All fields <span className="n num">{trackCount("")}</span></button>
              {TRACKS.map(([t, l]) => { const Icon = TRACK_ICON[t]; return <button key={t} className={`chip ${track === t ? "on" : ""}`} onClick={() => setTrack(t)}><Icon />{l}<span className="n num">{trackCount(t)}</span></button>; })}
            </div>
            <div className="chips">{WHERE.map(([v, l, Icon]) => <button key={l} className={`chip ${where === v ? "on" : ""}`} onClick={() => setWhere(v)}>{Icon && <Icon />}{l}</button>)}</div>
            <label className="search"><Search /><input placeholder="Company or title" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search internships" /></label>
            <label className="check"><input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} />Only new</label>
          </div>
          <Tabs value={tab} onChange={setTab} tabs={[["ok", "Qualify", uniq(ok)], ["out", "Filtered out", uniq(out)]]} />
          {tab === "out" && out.length > 0 && <p className="small muted" style={{ margin: "-.3rem 0 .8rem" }}>These missed one of your rules. If a recruiter tells you one is paid, or your coordinator says an IT internship counts, you can bring it back.</p>}
          <div className="list">
            {shown.length ? grouped.map(({ job, count }) => <InternRow key={job.id} job={job} count={count} onChange={reload} />) :
              <Empty title={tab === "out" ? "Nothing filtered out" : "None that qualify yet"}>
                {tab === "out" ? "Every internship found so far meets your rules." : "Try another field or place, check the sites below, or run the search again tomorrow. New spring postings appear through December."}</Empty>}
          </div>
        </>
      )}

      <div className="split sec">
        <section className="panel" id="sites">
          <SectionHead title="Search sites you log into" />
          <p className="small muted" style={{ margin: "-.3rem 0 .8rem" }}>Handshake, LinkedIn and Indeed don't allow automated searching, so these open the search in your own browser. Add anything good with the form.</p>
          {data?.links?.map((l: any) => (
            <div key={l.label} className="site">
              <div><b>{l.label}</b><div className="tiny muted">{l.why}</div></div>
              <div className="chips">{l.searches.map((s: any) => <a key={s.track} className="chip" href={s.url} target="_blank" rel="noreferrer">{s.label}<ExternalLink /></a>)}</div>
            </div>))}
          {data?.fixed_links?.map((l: any) => (
            <div key={l.label} className="site">
              <div><b>{l.label}</b><div className="tiny muted">{l.why}</div></div>
              <a className="chip" href={l.url} target="_blank" rel="noreferrer">Open<ExternalLink /></a>
            </div>))}
        </section>
        <AddInternship onAdded={(it) => { reload(); if (it?.intern?.status === "out") setTab("out"); }} />
      </div>
    </>
  );
}

function AddInternship({ onAdded }: { onAdded: (it: any) => void }) {
  const empty = { company_name: "", url: "", title: "", location: "", description: "" };
  const [f, setF] = useState<any>(empty);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<any>(null);
  async function add() {
    setErr(null); setBusy(true); setAdded(null);
    try { const it = await api("/api/internships", { body: f }); setF(empty); setAdded(it); onAdded(it); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  return (
    <section className="panel" id="add">
      <SectionHead title="Add one you found" />
      <p className="small muted" style={{ margin: "-.3rem 0 .8rem" }}>Company career pages and Greenhouse, Lever, Ashby or Workday links are read automatically. For Handshake or LinkedIn, paste the title and the posting text.</p>
      <div className="form">
        <label className="field">Company<input value={f.company_name} onChange={(e) => setF({ ...f, company_name: e.target.value })} /></label>
        <label className="field">Posting link<input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://" /></label>
        <label className="field">Title<input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        <label className="field">Location<input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} placeholder="Tempe, AZ or Remote" /></label>
      </div>
      <label className="field" style={{ marginTop: ".8rem" }}>Posting text<textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="Paste the whole posting so pay, hours and dates can be checked" /></label>
      <Err msg={err} />
      <div className="row" style={{ marginTop: ".7rem" }}>
        <button className="btn dark" onClick={add} disabled={busy}>{busy ? "Checking" : "Add and check it"}</button>
        {added && <span className="small">{added.intern?.status === "out" ? "Added to Filtered out: " + (added.intern.reasons_out?.[0] || "") : "Added. It qualifies."}</span>}
      </div>
    </section>
  );
}
