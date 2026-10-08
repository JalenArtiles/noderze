"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Err, Facts, OpportunityCard, RunButton } from "@/components/ui";
import { label, useApi } from "@/lib/api";

const SECTIONS: [string, string[]][] = [
  ["The program", ["program.name", "program.role_title", "program.description", "program.duration", "program.location", "program.work_mode"]],
  ["Pay", ["comp.base", "comp.variable", "comp.equity", "program.benefits"]],
  ["Training", ["program.training_content", "program.technologies", "program.certifications", "program.mentorship", "program.shadowing", "program.rotations", "program.customer_exposure"]],
  ["Eligibility", ["program.eligibility", "program.grad_window", "program.degree_req", "program.technical_req", "program.sales_req", "program.yoe"]],
  ["Where it leads", ["program.next_role", "program.conversion", "path.promotion_timeline", "program.outcomes"]],
  ["Timing", ["program.start_date", "program.open_window", "program.deadline", "program.rolling"]],
  ["Interview process", ["interview.process", "interview.stages", "interview.technical", "interview.presentation"]],
  ["Other", ["travel.percent", "intern.conversion", "review.sentiment"]],
];

export default function ProgramPage() {
  const { id } = useParams() as { id: string };
  const { data, error, reload } = useApi(`/api/programs/${id}`);
  if (error) return <Err msg={error} />;
  if (!data) return <p className="muted">Loading...</p>;
  const p = data.program;
  const ps = data.path_summary;
  return (
    <>
      <div className="small"><Link href={`/companies/${data.company.id}`}>{data.company.name}</Link></div>
      <h1>{p.name}</h1>
      <p>{p.summary}</p>
      <div className="row small"><span className={`badge ${p.status === "open" ? "good" : ""}`}>{label(p.status)}</span>
        <span>Trains toward: {p.target_family === "se" ? "Sales / Solutions Engineer" : p.target_family === "ae" ? "Account Executive" : "Mixed tracks"}</span>
        {p.typical_open_window && <span>Typically opens: {p.typical_open_window}</span>}
        <span>Confidence: <b>{p.confidence.overall}</b> ({p.confidence.official} of {p.confidence.facts} facts official)</span></div>
      <div className="row" style={{ marginTop: ".8rem" }}><RunButton kind="deep_research" body={{ company_id: data.company.id }} onDone={reload}>Research this program again</RunButton></div>
      <div className="grid2" style={{ marginTop: "1rem" }}>
        {SECTIONS.map(([title, fields]) => (
          <section key={title} className="panel"><h3>{title}</h3><Facts facts={p.facts} labels={data.field_labels} only={fields} /></section>))}
        <section className="panel"><h3>Observed progressions</h3>
          {ps.profiles ? <p className="small">{ps.profiles} profiles: {ps.reached_se} reached SE, {ps.transitions} from sales or technical entry roles{ps.median_months_to_se != null ? `, median ${ps.median_months_to_se} months` : ""}.</p>
            : <p className="small muted">No employee paths yet. Paste public profiles on the company page to build this evidence.</p>}
          {data.career_paths.map((c: any) => <div key={c.id} className="fact small"><b>{c.label}:</b> {c.steps.map((s: any) => s.title).join(" > ")}</div>)}
        </section>
        <section className="panel"><h3>Best way to stand out</h3>{data.standout.slice(0, 5).map((s: any, i: number) => <div key={i} className="fact small">{s.action}<div className="muted">{s.why}</div></div>)}</section>
        {!!data.concerns.length && <section className="panel"><h3>Potential concerns</h3>{data.concerns.map((c: string, i: number) => <div key={i} className="fact small">{c}</div>)}</section>}
      </div>
      <h2>Open roles linked to this program</h2>
      {data.jobs.length ? data.jobs.map((j: any) => <OpportunityCard key={j.id} job={j} />) : <p className="muted small">None found yet. Your Monday scan checks for new postings.</p>}
    </>
  );
}
