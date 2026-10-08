"use client";
import { useEffect, useMemo, useState } from "react";
import { Globe, MapPin, Search, Sun } from "lucide-react";
import { Err, OpportunityCard } from "@/components/ui";
import { api, useApi } from "@/lib/api";

const WHERE: [string, string, any][] = [["", "Anywhere", null], ["AZ", "Arizona", Sun], ["remote", "Remote", Globe], ["SOCAL", "Southern California", MapPin]];
const TYPES: [string, string][] = [["", "All types"], ["entry_sales", "Entry sales, cybersecurity"], ["program", "ASE and SE programs"], ["other_sales", "Entry sales, other tech"], ["goal_se", "SE roles to grow into"], ["technical_entry", "Technical entry"], ["long_shot", "Long shots"]];
const INDUSTRY: [string, string][] = [["", "All industries"], ["cybersecurity", "Cybersecurity"], ["software", "Software"], ["cloud_networking", "Cloud and networking"], ["ai", "AI"], ["it_solutions", "IT solutions"], ["public_safety", "Public safety"]];

export default function Opportunities() {
  const [f, setF] = useState({ where: "", category: "", industry: "", q: "", fits: true, fresh: false });
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setF({ where: p.get("remote") ? "remote" : p.get("state") || "", category: p.get("category") || "", industry: p.get("industry") || "",
      q: p.get("q") || "", fits: p.get("fits") !== "0", fresh: p.get("new") === "1" });
    setReady(true);
  }, []);
  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (f.where === "remote") p.set("remote", "true"); else if (f.where) p.set("state", f.where);
    if (f.category) p.set("category", f.category);
    if (f.industry) p.set("industry", f.industry);
    if (f.q) p.set("q", f.q);
    if (f.fits) p.set("fits", "true");
    if (f.fresh) p.set("new", "true");
    return p.toString();
  }, [f]);
  useEffect(() => { if (ready) window.history.replaceState(null, "", `/opportunities?${query.replace("remote=true", "remote=1").replace("new=true", "new=1")}${f.fits ? "" : "&fits=0"}`); }, [query, ready, f.fits]);
  const { data, error, reload } = useApi<any[]>(ready ? `/api/jobs?${query}` : null);
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  return (
    <>
      <h1>Opportunities</h1>
      <p className="muted">Pick what matters to you. Every card shows how directly the role leads to sales engineering.</p>
      <div className="filters">
        <div className="row"><span className="lab">Where</span><div className="chips">{WHERE.map(([v, l, Icon]) => <button key={l} className={`chip ${f.where === v ? "on" : ""}`} onClick={() => set("where", v)}>{Icon && <Icon />}{l}</button>)}</div></div>
        <div className="row"><span className="lab">Type</span><div className="chips">{TYPES.map(([v, l]) => <button key={l} className={`chip ${f.category === v ? "on" : ""}`} onClick={() => set("category", v)}>{l}</button>)}</div></div>
        <div className="row"><span className="lab">Industry</span><div className="chips">{INDUSTRY.map(([v, l]) => <button key={l} className={`chip ${f.industry === v ? "on" : ""}`} onClick={() => set("industry", v)}>{l}</button>)}</div></div>
        <div className="row"><span className="lab">Search</span>
          <span className="row" style={{ gap: ".3rem" }}><Search size={16} className="muted" /><input placeholder="Company, title or city" value={f.q} onChange={(e) => set("q", e.target.value)} style={{ minWidth: 240 }} /></span>
          <label className="small"><input type="checkbox" checked={f.fits} onChange={(e) => set("fits", e.target.checked)} /> Only roles that fit a May 2027 graduation</label>
          <label className="small"><input type="checkbox" checked={f.fresh} onChange={(e) => set("fresh", e.target.checked)} /> New since you last looked</label></div>
      </div>
      <Err msg={error} />
      <p className="small muted">{data ? `${data.length} ${data.length === 1 ? "match" : "matches"}, best first` : "Loading..."}</p>
      {data?.map((j) => <OpportunityCard key={j.id} job={j} onChange={reload} />)}
      {data && !data.length && <div className="panel empty">Nothing matches these filters yet. Try Anywhere, or run Find new jobs from Home.</div>}
      <AddJob onAdded={reload} />
    </>
  );
}

function AddJob({ onAdded }: { onAdded: () => void }) {
  const [f, setF] = useState<any>({ company_name: "", url: "", title: "", location: "", description: "" });
  const [err, setErr] = useState<string | null>(null);
  async function add() {
    setErr(null);
    try { await api("/api/jobs", { body: f }); setF({ company_name: "", url: "", title: "", location: "", description: "" }); onAdded(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <details className="panel" style={{ marginTop: "1.5rem" }}><summary style={{ cursor: "pointer", fontWeight: 650 }}>Add a job you found somewhere else</summary>
      <p className="small muted">Greenhouse, Lever and Ashby links are read from the company's own board. For anything else, paste the title and description.</p>
      <div className="grid2">
        <input placeholder="Company" value={f.company_name} onChange={(e) => setF({ ...f, company_name: e.target.value })} />
        <input placeholder="Posting URL" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
        <input placeholder="Title (if pasting)" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <input placeholder="Location (if pasting)" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} />
      </div>
      <textarea placeholder="Description (if pasting)" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} style={{ marginTop: ".6rem" }} />
      <Err msg={err} /><button className="btn" onClick={add} style={{ marginTop: ".5rem" }}>Add and score</button>
    </details>
  );
}
