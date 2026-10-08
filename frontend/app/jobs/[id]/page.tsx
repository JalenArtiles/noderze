"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Err, Fact, PathBadge, PathRail, RunButton, ScoreBars, Tabs, useTab } from "@/components/ui";
import { day, label, money, useApi } from "@/lib/api";
import { CompanyLogo, ScoreRing } from "@/components/visual";

export default function JobPage() {
  const { id } = useParams() as { id: string };
  const { data: j, error, reload } = useApi(`/api/jobs/${id}`);
  const [tab, setTab] = useTab("why");
  if (error) return <Err msg={error} />;
  if (!j) return <p className="muted">Loading...</p>;
  return (
    <>
      <div className="spread"><div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}><CompanyLogo name={j.company} website={j.company_website} size="lg" /><div>
        <div className="small"><Link href={`/companies/${j.company_id}`}>{j.company}</Link></div><h1>{j.title}</h1>
        <div className="row small"><PathBadge value={j.path_class} /><span>{j.location_text}</span><span className="badge">{label(j.remote_type)}</span>
          {j.comp_min && <span className="num">{money(j.comp_min)}{j.comp_max !== j.comp_min ? `-${money(j.comp_max)}` : ""}{j.comp_period === "hour" ? "/hr" : ""}</span>}
          <span className="badge" title={j.grad_reason}>{label(j.grad_status)}</span>
          {j.url && <a href={j.url} target="_blank" rel="noreferrer">{j.source_is_original ? "Original posting" : "Listing (not the original)"}</a>}</div>
        <div className="small muted">Found {day(j.discovered_at)}{j.last_verified_at ? `, verified active ${day(j.last_verified_at)}` : ", not yet verified live"}{j.posted_at ? `, posted ${day(j.posted_at)}` : ""}{!j.is_active ? ". Appears closed." : ""}</div>
      </div></div><ScoreRing value={j.score_total} size="lg" /></div>
      <PathRail job={j} />
      <Tabs tabs={[["why", "Why this role"], ["report", "Deep research"], ["prepare", "Prepare application"], ["posting", "Posting"]]} value={tab} onChange={setTab} />
      {tab === "why" && <Why j={j} />}
      {tab === "report" && <Report id={id} companyId={j.company_id} />}
      {tab === "prepare" && (
        <section className="panel stack">
          <p>Builds a tailored resume version (for your approval), cover letter, application answers, outreach drafts, interview prep, a study guide and a follow-up schedule. Nothing is sent or submitted.</p>
          {j.application_id && <p><Link href={`/applications/${j.application_id}`}>Open the existing application package</Link></p>}
          <RunButton kind="prepare_application" body={{ job_id: j.id }} className="btn primary" onDone={reload}>Prepare application</RunButton>
        </section>)}
      {tab === "posting" && <section className="panel"><pre style={{ whiteSpace: "pre-wrap", font: "inherit", margin: 0 }}>{j.description_text || "No posting text stored."}</pre></section>}
    </>
  );
}

function Why({ j }: { j: any }) {
  const a = j.analysis || {};
  return (
    <div className="grid2">
      <section className="panel"><h2 style={{ marginTop: 0 }}>Score breakdown</h2><ScoreBars breakdown={j.score_breakdown} /></section>
      <section className="panel stack">
        <h2 style={{ marginTop: 0 }}>Why it fits you</h2>
        {a.fits?.length ? a.fits.map((f: any, i: number) => <div key={i} className="fact"><b>{f.requirement}</b><div className="small muted">{f.evidence}</div></div>)
          : <p className="muted small">No requirements matched to your resume yet. Upload a resume or fetch the full posting.</p>}
        <h2>What you're missing</h2>
        {a.missing?.map((m: any, i: number) => <div key={i} className="fact"><b>{m.requirement}</b> <span className={`badge ${m.severity === "required" ? "bad" : "warn"}`}>{m.severity}</span>{m.note && <div className="small muted">{m.note}</div>}</div>)}
        <h2>How to compensate</h2>
        {[...(a.compensate || []).map((c: any) => ({ action: c.action, why: `Closes: ${c.for}` })), ...(j.standout || [])].slice(0, 7).map((s: any, i: number) => (
          <div key={i} className="fact">{s.action}<div className="small muted">{s.why}{s.effort ? `. Effort: ${s.effort}` : ""}</div></div>))}
      </section>
    </div>
  );
}

function Report({ id, companyId }: { id: string; companyId: number }) {
  const { data, error, reload } = useApi(`/api/jobs/${id}/report`);
  return (
    <section className="stack">
      <div className="row"><RunButton kind="deep_research" body={{ company_id: companyId, job_id: +id }} onDone={reload}>Run deep research</RunButton>
        {data && <span className="small muted">{data.confidence.facts} facts, {data.confidence.official} from official sources. Overall confidence: <b>{data.confidence.overall}</b></span>}</div>
      <Err msg={error} />
      {data && Object.entries(data.sections).map(([name, items]: any) => (
        <div key={name} className="panel"><h3>{name}</h3>
          {items.length ? items.map((f: any, i: number) => <div key={i} className="fact"><Fact f={f} /></div>) : <p className="small muted">Not found yet. Nothing is filled in without a source.</p>}
        </div>))}
    </section>
  );
}
