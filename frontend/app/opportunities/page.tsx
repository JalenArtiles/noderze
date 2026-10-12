"use client";
import { useEffect, useMemo, useState } from "react";
import { Globe, MapPin, Search, Sun } from "lucide-react";
import { Empty, Err, JobList, Loading, PageHeader, Tabs } from "@/components/ui";
import { api, useApi } from "@/lib/api";

const WHERE: [string, string, any][] = [["", "Anywhere", null], ["AZ", "Arizona", Sun], ["remote", "Remote", Globe], ["SOCAL", "Southern California", MapPin]];
const TYPES: [string, string][] = [["entry_sales", "Entry sales, cyber"], ["program", "ASE and SE programs"], ["other_sales", "Entry sales, other tech"],
  ["goal_se", "SE roles"], ["technical_entry", "Technical entry"], ["long_shot", "Long shots"], ["", "All"]];
const INDUSTRY: [string, string][] = [["", "All industries"], ["cybersecurity", "Cybersecurity"], ["software", "Software"], ["cloud_networking", "Cloud and networking"], ["ai", "AI"], ["it_solutions", "IT solutions"], ["public_safety", "Public safety"]];

export default function Opportunities() {
  const [f, setF] = useState({ where: "", category: "entry_sales", industry: "", q: "", fits: true, fresh: false });
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setF({ where: p.get("remote") ? "remote" : p.get("state") || "", category: p.has("category") ? p.get("category") || "" : (p.get("new") === "1" ? "" : "entry_sales"),
      industry: p.get("industry") || "", q: p.get("q") || "", fits: p.get("fits") !== "0", fresh: p.get("new") === "1" });
    setReady(true);
  }, []);
  // Category is filtered here so every tab can show its count; the rest is filtered by the server.
  const query = useMemo(() => {
    const p = new URLSearchParams({ limit: "1500", lite: "true" });
    if (f.where === "remote") p.set("remote", "true"); else if (f.where) p.set("state", f.where);
    if (f.industry) p.set("industry", f.industry);
    if (f.fits) p.set("fits", "true");
    if (f.fresh) p.set("new", "true");
    return p.toString();
  }, [f.where, f.industry, f.fits, f.fresh]);
  useEffect(() => {
    if (!ready) return;
    const p = new URLSearchParams();
    if (f.where === "remote") p.set("remote", "1"); else if (f.where) p.set("state", f.where);
    if (f.category !== "entry_sales") p.set("category", f.category);
    if (f.industry) p.set("industry", f.industry);
    if (!f.fits) p.set("fits", "0");
    if (f.fresh) p.set("new", "1");
    if (f.q) p.set("q", f.q);
    window.history.replaceState(null, "", `/opportunities${p.toString() ? `?${p}` : ""}`);
  }, [f, ready]);
  const { data, error, reload } = useApi<any[]>(ready ? `/api/jobs?${query}` : null);
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const searched = useMemo(() => (data || []).filter((j) => !f.q || `${j.title} ${j.company} ${j.location_text || ""}`.toLowerCase().includes(f.q.toLowerCase())), [data, f.q]);
  const counts = useMemo(() => { const c: Record<string, number> = { "": searched.length }; searched.forEach((j) => { c[j.category] = (c[j.category] || 0) + 1; }); return c; }, [searched]);
  const shown = f.category ? searched.filter((j) => j.category === f.category) : searched;
  return (
    <>
      <PageHeader title="All roles" lede="Every role Noderze found, scored for how well it fits you and how directly it leads to sales engineering." />
      <div className="toolbar">
        <div className="chips">{WHERE.map(([v, l, Icon]) => <button key={l} className={`chip ${f.where === v ? "on" : ""}`} onClick={() => set("where", v)}>{Icon && <Icon />}{l}</button>)}</div>
        <select value={f.industry} onChange={(e) => set("industry", e.target.value)} aria-label="Industry">{INDUSTRY.map(([v, l]) => <option key={l} value={v}>{l}</option>)}</select>
        <label className="search"><Search /><input placeholder="Company, title or city" value={f.q} onChange={(e) => set("q", e.target.value)} aria-label="Search roles" /></label>
      </div>
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <label className="check"><input type="checkbox" checked={f.fits} onChange={(e) => set("fits", e.target.checked)} />Only roles that fit a May 2027 graduation</label>
        <label className="check"><input type="checkbox" checked={f.fresh} onChange={(e) => set("fresh", e.target.checked)} />Only new since you last looked</label>
      </div>
      <Tabs value={f.category} onChange={(v) => set("category", v)} tabs={TYPES.map(([k, l]) => [k, l, data ? counts[k] || 0 : null] as [string, string, number | null])} />
      <Err msg={error} />
      {!data ? <Loading what="Loading roles" /> : <JobList jobs={shown} page={25} onChange={reload}
        empty={<Empty title="Nothing matches these filters">Try Anywhere, another type, or turn off the graduation filter.</Empty>} />}
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
    <details className="panel more-info" style={{ marginTop: "1.6rem" }}><summary>Add a role you found somewhere else</summary>
      <p className="small muted" style={{ marginBottom: ".8rem" }}>Greenhouse, Lever and Ashby links are read from the company's own board. For anything else, paste the title and description.</p>
      <div className="form">
        <label className="field">Company<input value={f.company_name} onChange={(e) => setF({ ...f, company_name: e.target.value })} /></label>
        <label className="field">Posting link<input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></label>
        <label className="field">Title (if pasting)<input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        <label className="field">Location (if pasting)<input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></label>
      </div>
      <label className="field" style={{ marginTop: ".8rem" }}>Description (if pasting)<textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
      <Err msg={err} /><button className="btn dark" onClick={add} style={{ marginTop: ".7rem" }}>Add and score</button>
    </details>
  );
}
