"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ExternalLink } from "lucide-react";
import { Empty, Err, Fact, GRAD_SHORT, Loading, Menu, PageHeader, PathBadge, PathRail, RunButton, ScoreBars, Tabs, compText, useTab } from "@/components/ui";
import { useActivity } from "@/components/activity";
import { day, label, useApi } from "@/lib/api";
import { CompanyLogo, ScoreRing } from "@/components/visual";
import { FactChips, InternChecks } from "@/components/intern";

export default function JobPage() {
  const { id } = useParams() as { id: string };
  const { data: j, error, reload } = useApi(`/api/jobs/${id}`);
  const [tab, setTab] = useTab("why");
  const act = useActivity();
  if (error) return <Err msg={error} />;
  if (!j) return <Loading />;
  const comp = compText(j);
  const intern = j.family === "internship" && j.intern;
  return (
    <>
      <PageHeader
        crumb={intern ? <><Link href="/internships">Spring internships</Link>, <Link href={`/companies/${j.company_id}`}>{j.company}</Link></> : <Link href={`/companies/${j.company_id}`}>{j.company}</Link>}
        title={<span className="ph-id"><CompanyLogo name={j.company} website={j.company_website} size="lg" /><span>{j.title}</span></span>}
        actions={<>
          <ScoreRing value={j.score_total} />
          <Link className="btn primary" href={`/apply/${j.id}`}>Apply</Link>
          <Menu>
            {j.url && <a href={j.url} target="_blank" rel="noreferrer">{j.source_is_original ? "Open the original posting" : "Open the listing"}</a>}
            <button onClick={() => act.start({ kind: "prepare_application", body: { job_id: j.id }, label: `${j.company}, ${j.title}`, onDone: reload })}>Prepare the full package<span className="d">Cover letter, answers, interview prep</span></button>
            <button onClick={() => act.start({ kind: "deep_research", body: { company_id: j.company_id, job_id: j.id }, label: j.company, onDone: reload })}>Research this company<span className="d">Sourced facts from the web</span></button>
            {intern && <Link href={`/apply/${j.id}#recruiter`}>Reach the recruiter<span className="d">LinkedIn searches and a message to copy</span></Link>}
            {intern && <button onClick={() => act.start({ kind: "find_recruiters", body: { company_id: j.company_id, mode: "intern" }, label: `${j.company} recruiters`, onDone: reload })}>Find recruiters and team managers<span className="d">Public profiles, unverified until you check them</span></button>}
            {j.application_id && <Link href={`/applications/${j.application_id}`}>Open the application</Link>}
          </Menu>
        </>}>
        {intern ? <div className="meta"><span className={`tag track ${intern.track}`}>{intern.track_label}</span><FactChips it={intern} />
          {!j.is_active && <span className="tag bad">Appears closed</span>}</div> : <div className="meta">
          <PathBadge value={j.path_class} />
          <span className="tag">{j.location_text || "Location unknown"}</span>
          {j.remote_type !== "unknown" && <span className="tag">{label(j.remote_type)}</span>}
          {comp && <span className="tag num">{comp}</span>}
          {j.grad_status && <span className="tag" title={j.grad_reason}>{GRAD_SHORT[j.grad_status] || label(j.grad_status)}</span>}
          {!j.is_active && <span className="tag bad">Appears closed</span>}
        </div>}
        <p className="small faint" style={{ marginTop: ".5rem" }}>Found {day(j.discovered_at)}{j.last_verified_at ? `, still open as of ${day(j.last_verified_at)}` : ", not checked live yet"}{j.posted_at ? `, posted ${day(j.posted_at)}` : ""}.</p>
      </PageHeader>
      {intern ? <div style={{ marginTop: ".4rem" }}><InternChecks job={j} onChange={reload} /></div> : <PathRail job={j} />}
      <Tabs value={tab} onChange={setTab} tabs={[["why", intern ? "Why it fits" : "Why this role"], ["report", "Research"], ["posting", "Posting"]]} />
      {tab === "why" && <Why j={j} />}
      {tab === "report" && <Report id={id} companyId={j.company_id} company={j.company} />}
      {tab === "posting" && <section className="panel"><pre style={{ whiteSpace: "pre-wrap", font: "inherit", margin: 0, maxWidth: "80ch" }}>{j.description_text || "No posting text stored."}</pre></section>}
    </>
  );
}

function Why({ j }: { j: any }) {
  const a = j.analysis || {};
  const ideas = [...(a.compensate || []).map((c: any) => ({ action: c.action, why: `Closes: ${c.for}` })), ...(j.standout || [])].slice(0, 6);
  return (
    <div className="split">
      <div className="stack-lg">
        <section className="panel">
          <h3 style={{ marginBottom: ".7rem" }}>Where you match</h3>
          {a.fits?.length ? a.fits.map((f: any, i: number) => <div key={i} className="fact"><b>{f.requirement}</b><div className="small muted">{f.evidence}</div></div>)
            : <p className="muted small">Nothing matched to your resume yet. Upload a resume, or open the posting to load its full text.</p>}
        </section>
        {a.missing?.length > 0 && <section className="panel">
          <h3 style={{ marginBottom: ".7rem" }}>Gaps</h3>
          {a.missing.map((m: any, i: number) => <div key={i} className="fact"><div className="row"><b>{m.requirement}</b><span className={`tag ${m.severity === "required" ? "bad" : "warn"}`}>{m.severity}</span></div>{m.note && <div className="small muted">{m.note}</div>}</div>)}
        </section>}
        {ideas.length > 0 && <section className="panel">
          <h3 style={{ marginBottom: ".7rem" }}>How to close the gaps</h3>
          {ideas.map((s: any, i: number) => <div key={i} className="fact">{s.action}<div className="small muted">{(s.why || "").replace(/\.$/, "")}{s.effort ? `. About ${s.effort}.` : "."}</div></div>)}
        </section>}
      </div>
      <section className="panel">
        <h3>Score breakdown</h3>
        <p className="small muted" style={{ margin: ".25rem 0 .9rem" }}>Click a line to see the reasons.</p>
        <ScoreBars breakdown={j.score_breakdown} />
      </section>
    </div>
  );
}

function Report({ id, companyId, company }: { id: string; companyId: number; company: string }) {
  const { data, error, reload } = useApi(`/api/jobs/${id}/report`);
  if (error) return <Err msg={error} />;
  if (!data) return <Loading />;
  const sections = Object.entries(data.sections) as [string, any[]][];
  const found = sections.filter(([, items]) => items.length);
  const missing = sections.filter(([, items]) => !items.length).map(([n]) => n);
  return (
    <div className="stack-lg">
      <div className="row">
        <RunButton kind="deep_research" body={{ company_id: companyId, job_id: +id }} label={company} className="btn dark" onDone={reload}>Research {company}</RunButton>
        <span className="small muted">{data.confidence.facts} sourced facts, {data.confidence.official} from official sources. Confidence: {data.confidence.overall}.</span>
      </div>
      {found.length ? <div className="grid2">{found.map(([name, items]) => (
        <section key={name} className="panel"><h3 style={{ marginBottom: ".6rem" }}>{name}</h3>{items.map((f: any, i: number) => <div key={i} className="fact"><Fact f={f} /></div>)}</section>))}</div>
        : <div className="panel"><Empty title="No research yet">Research collects facts about pay, the team, the interview process and the path to SE, each with its source.</Empty></div>}
      {missing.length > 0 && found.length > 0 && <p className="small faint">Not found yet: {missing.join(", ")}. Nothing is filled in without a source.</p>}
    </div>
  );
}
