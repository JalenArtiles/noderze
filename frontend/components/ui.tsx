"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, day, label, money } from "@/lib/api";
import { MapPin } from "lucide-react";
import { CompanyLogo, ScoreRing } from "@/components/visual";

export function Err({ msg }: { msg?: string | null }) { return msg ? <div className="error" role="alert">{msg}</div> : null; }

export function PathBadge({ value }: { value?: string | null }) {
  if (!value) return null;
  return <span className={`path ${value}`} title={PATH_HELP[value]}>{value}</span>;
}
const PATH_HELP: Record<string, string> = {
  DIRECT: "A formal program or the role itself trains you into SE",
  LIKELY: "Strong evidence of internal transitions into SE",
  POSSIBLE: "Company has SEs and supports mobility, little transition evidence",
  WEAK: "No meaningful evidence of a path into SE",
};

export function PathRail({ job }: { job: any }) {
  const cls = job.path_class || "WEAK";
  let stops: string[];
  if (job.family === "direct_se" && job.is_program) stops = ["You, May 2027", job.program_name || "Program", "Solutions / Sales Engineer"];
  else if (job.family === "direct_se") stops = ["You, May 2027", shortTitle(job.title), "Senior SE"];
  else if (job.family === "pipeline") stops = ["You, May 2027", shortTitle(job.title), cls === "WEAK" ? "SE (unproven)" : "Sales Engineer"];
  else stops = ["You, May 2027", shortTitle(job.title), "Sales Engineer"];
  return (
    <div className={`rail ${cls}`} aria-label={`Career path: ${stops.join(", then ")} (${cls})`}>
      {stops.map((s, i) => (
        <span key={i} style={{ display: "contents" }}>
          {i > 0 && <span className="seg" />}
          <span className={`stop ${i === stops.length - 1 ? "end" : ""}`}><span className="dot" /><span className="label">{s}</span></span>
        </span>
      ))}
    </div>
  );
}
const shortTitle = (t: string) => (t || "").split(/[,(]/)[0].slice(0, 40);

export function ScoreBars({ breakdown }: { breakdown: Record<string, any> }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!breakdown) return null;
  return (
    <div className="bars">
      {Object.entries(breakdown).map(([k, c]: any) => (
        <div key={k} style={{ display: "contents" }}>
          <button onClick={() => setOpen(open === k ? null : k)} style={{ all: "unset", cursor: "pointer" }} aria-expanded={open === k}>{c.label}</button>
          <div className="bar"><i style={{ width: `${c.max ? (100 * c.score) / c.max : 0}%` }} /></div>
          <span className="num">{c.score}/{Math.round(c.max)}</span>
          {open === k && <div className="reasons">{c.reasons.map((r: string, i: number) => <div key={i}>{r}</div>)}</div>}
        </div>
      ))}
    </div>
  );
}

const GRAD_TONE: Record<string, string> = { eligible_now: "good", likely_may_2027: "good", eligible_closer: "", internship_convert: "warn",
  too_early: "bad", too_late: "bad", requires_experience: "warn", unclear: "" };
export const CAT_LABEL: Record<string, string> = { entry_sales: "Entry sales, cybersecurity", program: "ASE role or SE program",
  other_sales: "Entry sales, other tech", goal_se: "SE role to grow into", technical_entry: "Technical entry role",
  long_shot: "Long shot or outside your area", direct_se: "Direct SE role", pipeline: "Sales role toward SE" };
export const GRAD_SHORT: Record<string, string> = { eligible_now: "Eligible now", likely_may_2027: "Made for 2027 grads", eligible_closer: "Apply closer to your start",
  internship_convert: "Internship", too_early: "Starts before you graduate", too_late: "For later graduates", requires_experience: "Needs experience", unclear: "Timing unclear" };

export function OpportunityCard({ job, onChange }: { job: any; onChange?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const comp = job.comp_min ? `${money(job.comp_min)}${job.comp_max && job.comp_max !== job.comp_min ? `-${money(job.comp_max)}` : ""}${job.comp_period === "hour" ? "/hr" : ""}` : null;
  async function track() {
    setBusy(true);
    try { await api("/api/applications", { body: { job_id: job.id } }); onChange?.(); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  return (
    <article className={`card ${job.category || ""}`}>
      <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap", gap: ".9rem" }}>
        <CompanyLogo name={job.company} website={job.company_website} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="row small"><span className="cat">{CAT_LABEL[job.category] || ""}</span><span className="muted">{job.company}</span>
            {job.sales_level && <span className="badge">{job.sales_level}</span>}
            {job.se_roles_seen > 0 && <span className="badge good" title="Open SE or solutions roles on the company's own job board">SE team: {job.se_roles_seen} open roles</span>}
            {job.flags?.includes("outside_area") && <span className="badge warn">Outside your area</span>}
            {job.flags?.includes("edge_location") && <span className="badge warn">Edge location</span>}
            {job.needs_verification && <span className="badge">Verify posting</span>}{job.application_stage && <span className="badge good">{label(job.application_stage)}</span>}</div>
          <h3 style={{ margin: ".15rem 0 .25rem", fontSize: "1.08rem" }}><Link href={`/jobs/${job.id}`} style={{ color: "var(--ink)" }}>{job.title}</Link></h3>
          <div className="row small">
            <span className="badge"><MapPin size={13} />{job.location_text || "Location unknown"}</span>
            {job.remote_type !== "unknown" && <span className="badge">{label(job.remote_type)}</span>}
            {comp && <span className="badge num">{comp}</span>}
            {job.grad_status && <span className={`badge ${GRAD_TONE[job.grad_status] || ""}`} title={job.grad_reason}>{GRAD_SHORT[job.grad_status] || label(job.grad_status)}</span>}
            {job.deadline && <span className="badge warn">Due {day(job.deadline)}</span>}
            <PathBadge value={job.path_class} />
          </div>
          <PathRail job={job} />
        </div>
        <ScoreRing value={job.score_total} />
      </div>
      <Err msg={err} />
      <div className="row" style={{ marginTop: ".55rem" }}>
        <Link className="btn primary small" href={`/apply/${job.id}`}>Apply</Link>
        <Link className="btn secondary small" href={`/apply/${job.id}#recruiter`}>Find recruiter</Link>
        <Link className="btn secondary small" href={`/jobs/${job.id}`}>Why it fits</Link>
        <Link className="btn secondary small" href={`/jobs/${job.id}?tab=report`}>Research</Link>
        {!job.application_stage && <button className="btn secondary small" disabled={busy} onClick={track}>Add to tracker</button>}
      </div>
    </article>
  );
}

export function RunButton({ kind, body, children, onDone, className = "btn" }: { kind: string; body?: any; children: any; onDone?: (run: any) => void; className?: string }) {
  const [run, setRun] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setErr(null);
    try {
      const { run_id } = await api(`/api/workflows/${kind}`, { body: body || {} });
      let r: any;
      do { await new Promise((ok) => setTimeout(ok, 1500)); r = await api(`/api/runs/${run_id}`); setRun(r); } while (r.status === "running");
      onDone?.(r);
    } catch (e: any) { setErr(e.message); }
  }
  const running = run?.status === "running";
  return (
    <div className="stack" style={{ display: "inline-block", verticalAlign: "top", maxWidth: "100%" }}>
      <button className={className} onClick={go} disabled={running}>{running ? "Working..." : children}</button>
      <Err msg={err || run?.error} />
      {run && <div className="log" aria-live="polite">{run.log.map((l: any) => l.msg).join("\n") || "Starting..."}{run.status !== "running" ? `\n[${run.status}]` : ""}</div>}
    </div>
  );
}

export function Facts({ facts, labels, only }: { facts: Record<string, any[]>; labels?: Record<string, string>; only?: string[] }) {
  const keys = (only || Object.keys(facts || {})).filter((k) => facts?.[k]?.length);
  if (!keys.length) return <p className="muted small">No sourced facts yet. Run Deep research, or add a fact you verified.</p>;
  return (
    <dl className="facts">
      {keys.map((k) => (
        <div key={k}><dt>{labels?.[k] || label(k.split(".").pop())}</dt>
          {facts[k].map((f: any, i: number) => <dd key={i} className="fact"><Fact f={f} /></dd>)}</div>
      ))}
    </dl>
  );
}

export function Fact({ f }: { f: any }) {
  return (
    <div>
      <div>{f.value}</div>
      <div className="row small muted">
        <span className={`badge ${f.source_type}`}>{label(f.source_type)}</span><span className="badge">{f.confidence} confidence</span>
        {f.corroborated_by > 0 && <span>+{f.corroborated_by} agreeing</span>}
        {f.observed_on && <span>as of {day(f.observed_on)}</span>}
        {f.source?.url && <a href={f.source.url} target="_blank" rel="noreferrer">{f.source.title || f.source.publisher || "source"}</a>}
        {f.note && <span title={f.note}>Note: {f.note}</span>}
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: [string, string][]; value: string; onChange: (v: string) => void }) {
  return <div className="tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>{l}</button>)}</div>;
}

/** Reads ?tab= once on mount (avoids useSearchParams Suspense requirements in static builds). */
export function useTab(initial: string): [string, (t: string) => void] {
  const [tab, setTab] = useState(initial);
  useEffect(() => { const t = new URLSearchParams(window.location.search).get("tab"); if (t) setTab(t); }, []);
  return [tab, setTab];
}
