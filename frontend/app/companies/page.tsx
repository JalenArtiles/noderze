"use client";
import Link from "next/link";
import { useState } from "react";
import { Globe, MapPin, Plus, Search, Sun } from "lucide-react";
import { Empty, Err, Loading, PageHeader, ScoreChip } from "@/components/ui";
import { CompanyLogo } from "@/components/visual";
import { api, useApi } from "@/lib/api";

const WATCH: [string, string][] = [["priority", "Priority"], ["strong", "Strong target"], ["monitor", "Watching"], ["edge", "Edge case"], ["not_relevant", "Not relevant"]];
const VIEWS: [string, string][] = [["hiring", "Hiring near you"], ["se", "Has an SE team"], ["all", "All"]];

export default function Companies() {
  const [cyber, setCyber] = useState(true);
  const [view, setView] = useState("hiring");
  const [q, setQ] = useState("");
  const { data, error, reload } = useApi<any[]>(`/api/company-board?cyber=${cyber}`);
  const [name, setName] = useState(""); const [err, setErr] = useState<string | null>(null);
  const all = data || [];
  const counts: Record<string, number> = { hiring: all.filter((c) => c.entry_count > 0).length, se: all.filter((c) => c.se_team.known).length, all: all.length };
  const list = all.filter((c) => (view !== "hiring" || c.entry_count > 0) && (view !== "se" || c.se_team.known) &&
    (!q || `${c.name} ${c.subcategory || ""}`.toLowerCase().includes(q.toLowerCase())));
  async function setStatus(id: number, v: string) { await api(`/api/companies/${id}`, { method: "PATCH", body: { watch_status: v || null } }); reload(); }
  async function add() { try { await api("/api/companies", { body: { name, category: cyber ? "cybersecurity" : null } }); setName(""); setErr(null); reload(); } catch (e: any) { setErr(e.message); } }
  return (
    <>
      <PageHeader title="Companies" lede="Cybersecurity companies with entry sales roles near you and an SE team to grow into, best fit first." />
      <div className="toolbar">
        <div className="chips">{VIEWS.map(([k, l]) => <button key={k} className={`chip ${view === k ? "on" : ""}`} onClick={() => setView(k)}>{l}<span className="n">{data ? counts[k] : ""}</span></button>)}</div>
        <label className="search"><Search /><input placeholder="Search companies" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search companies" /></label>
        <label className="check" style={{ marginLeft: "auto" }}><input type="checkbox" checked={!cyber} onChange={(e) => setCyber(!e.target.checked)} />Include non-security companies</label>
      </div>
      <Err msg={error || err} />
      {!data ? <Loading /> : !list.length ? <div className="panel"><Empty title="No companies match">Try All, or clear the search.</Empty></div> : (
        <div className="board">
          {list.map((c) => (
            <article key={c.id} className={`co ${c.entry_count ? "has-roles" : ""}`}>
              <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start", gap: ".8rem" }}>
                <CompanyLogo name={c.name} website={c.website} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Link href={`/companies/${c.id}`} style={{ color: "var(--ink)", fontWeight: 700, fontSize: "1.05rem" }}>{c.name}</Link>
                  <div className="small muted" style={{ lineHeight: 1.35 }}>{c.subcategory || "Cybersecurity"}</div>
                </div>
                <select className="watch" value={c.watch_status || ""} onChange={(e) => setStatus(c.id, e.target.value)} aria-label={`Watch status for ${c.name}`}>
                  {WATCH.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
              </div>
              <div className="meta" style={{ marginTop: 0 }}>
                {c.presence.az && <span className="tag good"><Sun />Arizona</span>}
                {c.presence.remote && <span className="tag good"><Globe />Remote</span>}
                {c.presence.socal && <span className="tag good"><MapPin />SoCal</span>}
                {c.se_team.known ? <span className="tag info" title={(c.se_team.sample || []).join("; ")}>{c.se_team.open_roles ? `${c.se_team.open_roles} open SE roles` : "SE team confirmed"}</span>
                  : <span className="tag">SE team unknown</span>}
                {c.programs > 0 && <span className="tag new">SE program</span>}
              </div>
              {c.entry_roles.length > 0 ? (
                <div className="roles">
                  {c.entry_roles.slice(0, 3).map((r: any) => (
                    <Link key={r.id} href={`/apply/${r.id}`}>
                      <span style={{ minWidth: 0 }}><span className="t">{r.title}</span><span className="w">{[r.level?.split(" (")[0], r.location].filter(Boolean).join(", ")}</span></span>
                      <ScoreChip value={r.score} />
                    </Link>))}
                </div>) : <p className="small muted">No entry sales roles near you right now. It's rescanned every three hours.</p>}
              <div className="foot">
                <Link className="small" href={`/companies/${c.id}`}>{c.entry_count > 3 ? `All ${c.entry_count} roles` : "Company details"}</Link>
                {c.best && <Link className="btn sm primary" href={`/apply/${c.best.id}`}>Apply to best match</Link>}
              </div>
            </article>))}
        </div>)}
      <section className="panel row" style={{ marginTop: "1.6rem", justifyContent: "space-between" }}>
        <div><h3>Watch another company</h3><p className="small muted">Its job board is found automatically on the next scan.</p></div>
        <div className="row"><input placeholder="Company name" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && name && add()} />
          <button className="btn dark" onClick={add} disabled={!name}><Plus />Add</button></div>
      </section>
    </>
  );
}
