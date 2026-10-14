"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Info, Loader2, MoreHorizontal } from "lucide-react";
import { api, day, label, money } from "@/lib/api";
import { CompanyLogo } from "@/components/visual";
import { useActivity } from "@/components/activity";

export function Err({ msg }: { msg?: string | null }) { return msg ? <div className="error" role="alert">{msg}</div> : null; }

export function PageHeader({ title, lede, crumb, actions, children }: { title: React.ReactNode; lede?: React.ReactNode; crumb?: React.ReactNode; actions?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <header className="ph">
      <div style={{ minWidth: 0, flex: "1 1 420px" }}>
        {crumb && <span className="crumb">{crumb}</span>}
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
        {children}
      </div>
      {actions && <div className="ph-actions">{actions}</div>}
    </header>
  );
}

export function SectionHead({ title, count, aside }: { title: React.ReactNode; count?: number | null; aside?: React.ReactNode }) {
  return <div className="sec-head"><h2>{title}{count != null && <span className="n num">{count}</span>}</h2>{aside && <div className="aside">{aside}</div>}</div>;
}

export function Empty({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return <div className="empty"><h3>{title}</h3>{children && <p>{children}</p>}{action}</div>;
}

export function Callout({ tone, children, action }: { tone?: "warn" | "bad"; children: React.ReactNode; action?: React.ReactNode }) {
  return <div className={`callout ${tone || ""}`}>{tone ? <AlertTriangle /> : <Info />}<div className="grow">{children}</div>{action}</div>;
}

export function Loading({ what = "Loading" }: { what?: string }) { return <p className="skeleton">{what}...</p>; }

/** A small "more actions" menu so a screen keeps one obvious primary action. */
export function Menu({ label: lab = "More actions", children }: { label?: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) ref.current.open = false; };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  return (
    <details className="menu" ref={ref}>
      <summary className="btn" aria-label={lab}><MoreHorizontal /></summary>
      <div className="pop" onClick={() => { if (ref.current) ref.current.open = false; }}>{children}</div>
    </details>
  );
}

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
          <button onClick={() => setOpen(open === k ? null : k)} aria-expanded={open === k}>{c.label}</button>
          <div className="bar"><i style={{ width: `${c.max ? (100 * c.score) / c.max : 0}%` }} /></div>
          <span className="num small">{c.score}/{Math.round(c.max)}</span>
          {open === k && <div className="reasons">{c.reasons.map((r: string, i: number) => <div key={i}>{r}</div>)}</div>}
        </div>
      ))}
    </div>
  );
}

export function ScoreChip({ value }: { value?: number | null }) {
  const v = Math.round(value || 0);
  return <span className={`score-chip ${v >= 75 ? "hi" : v >= 60 ? "mid" : "lo"}`} title={`Fit score ${v} out of 100`}>{v}</span>;
}

const GRAD_TONE: Record<string, string> = { eligible_now: "good", likely_may_2027: "good", eligible_closer: "", internship_convert: "warn",
  too_early: "bad", too_late: "bad", requires_experience: "warn", unclear: "" };
export const CAT_LABEL: Record<string, string> = { entry_sales: "Entry sales, cybersecurity", program: "ASE role or SE program",
  other_sales: "Entry sales, other tech", goal_se: "SE role to grow into", technical_entry: "Technical entry role",
  long_shot: "Long shot or outside your area", direct_se: "Direct SE role", pipeline: "Sales role toward SE",
  spring_intern: "Spring internship", intern_out: "Internship, filtered out" };
export const GRAD_SHORT: Record<string, string> = { eligible_now: "Eligible now", likely_may_2027: "Made for 2027 grads", eligible_closer: "Apply closer to your start",
  internship_convert: "Internship", too_early: "Starts before you graduate", too_late: "For later graduates", requires_experience: "Needs experience", unclear: "Timing unclear" };

export const compText = (job: any) => job.comp_min ? `${money(job.comp_min)}${job.comp_max && job.comp_max !== job.comp_min ? `-${money(job.comp_max)}` : ""}${job.comp_period === "hour" ? "/hr" : ""}` : null;

/** One role as a compact row: what it is, where, the few facts that decide whether to click, and the score. */
export function JobRow({ job, showCompany = true, onChange }: { job: any; showCompany?: boolean; onChange?: () => void }) {
  const [busy, setBusy] = useState(false);
  const comp = compText(job);
  const where = [showCompany ? job.company : null, job.location_text || "Location unknown", comp].filter(Boolean).join(", ");
  const grad = job.grad_status && job.grad_status !== "unclear" ? job.grad_status : null;
  async function track() { setBusy(true); try { await api("/api/applications", { body: { job_id: job.id } }); onChange?.(); } catch {} setBusy(false); }
  return (
    <div className="li hover">
      {showCompany && <CompanyLogo name={job.company} website={job.company_website} size="sm" />}
      <div className="grow">
        <Link href={`/jobs/${job.id}`} className="title" style={{ display: "block" }}>{job.title}</Link>
        <div className="sub">{where}</div>
        <div className="meta" style={{ marginTop: ".4rem" }}>
          <PathBadge value={job.path_class} />
          {job.application_stage ? <span className="tag good">{label(job.application_stage)}</span>
            : grad && <span className={`tag ${GRAD_TONE[grad] || ""}`} title={job.grad_reason}>{GRAD_SHORT[grad] || label(grad)}</span>}
          {job.flags?.includes("outside_area") ? <span className="tag warn">Outside your area</span>
            : job.sales_level ? <span className="tag">{job.sales_level.split(" (")[0]}</span>
            : job.category === "program" ? <span className="tag brand">Program</span> : null}
          {job.deadline && <span className="tag warn">Due {day(job.deadline)}</span>}
        </div>
      </div>
      <div className="end">
        <ScoreChip value={job.score_total} />
        {!job.application_stage && onChange && <button className="btn sm quiet" onClick={track} disabled={busy}>Save</button>}
        <Link className="btn sm primary" href={`/apply/${job.id}`}>Apply</Link>
      </div>
    </div>
  );
}

/** Paged list of roles: shows `page` at a time with a "show more" footer. */
export function JobList({ jobs, page = 20, showCompany = true, onChange, empty }: { jobs: any[]; page?: number; showCompany?: boolean; onChange?: () => void; empty?: React.ReactNode }) {
  const [n, setN] = useState(page);
  useEffect(() => setN(page), [jobs, page]);
  if (!jobs.length) return <div className="list">{empty || <Empty title="No roles here yet" />}</div>;
  return (
    <div className="list">
      {jobs.slice(0, n).map((j) => <JobRow key={j.id} job={j} showCompany={showCompany} onChange={onChange} />)}
      {jobs.length > n && <div className="more"><button className="btn sm" onClick={() => setN(n + page)}>Show {Math.min(page, jobs.length - n)} more of {jobs.length - n} left</button></div>}
    </div>
  );
}

/** Starts a workflow and shows its progress in the activity panel. */
export function RunButton({ kind, body, children, onDone, className = "btn", label: lab = "", quiet = false }: { kind: string; body?: any; children: any; onDone?: (run: any) => void; className?: string; label?: string; quiet?: boolean }) {
  const act = useActivity();
  const [err, setErr] = useState<string | null>(null);
  const key = `${kind}:${JSON.stringify(body || {})}`;
  const running = act.isRunning(key);
  return (
    <>
      <button className={className} disabled={running} onClick={() => { setErr(null); act.start({ kind, body, label: lab || label(kind), key, quiet, onDone }).catch((e) => setErr(e.message)); }}>
        {running ? <><Loader2 className="spin" style={{ animation: "spin 1s linear infinite" }} />Running</> : children}
      </button>
      {err && <span className="small" style={{ color: "var(--red)" }}>{err}</span>}
    </>
  );
}

export function Facts({ facts, labels, only, empty }: { facts: Record<string, any[]>; labels?: Record<string, string>; only?: string[]; empty?: React.ReactNode }) {
  const keys = (only || Object.keys(facts || {})).filter((k) => facts?.[k]?.length);
  if (!keys.length) return <>{empty ?? <p className="muted small">No sourced facts yet.</p>}</>;
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
      <div className="src">
        <span className={`tag ${f.source_type}`}>{label(f.source_type)}</span><span>{f.confidence} confidence</span>
        {f.corroborated_by > 0 && <span>{f.corroborated_by} other sources agree</span>}
        {f.observed_on && <span>as of {day(f.observed_on)}</span>}
        {f.source?.url && <a href={f.source.url} target="_blank" rel="noreferrer">{f.source.title || f.source.publisher || "Source"}</a>}
        {f.note && <span title={f.note}>Note: {f.note}</span>}
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: ([string, string] | [string, string, number | null])[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([k, l, n]) => (
        <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => { onChange(k); const u = new URL(window.location.href); u.searchParams.set("tab", k); window.history.replaceState(null, "", u.toString()); }}>
          {l}{n != null && <span className="n num">{n}</span>}
        </button>))}
    </div>
  );
}

/** Reads ?tab= once on mount (avoids useSearchParams Suspense requirements in static builds). */
export function useTab(initial: string): [string, (t: string) => void] {
  const [tab, setTab] = useState(initial);
  useEffect(() => { const t = new URLSearchParams(window.location.search).get("tab"); if (t) setTab(t); }, []);
  return [tab, setTab];
}
