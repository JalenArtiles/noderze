"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Callout, Err, Facts, JobList, Loading, PageHeader, RunButton, SectionHead } from "@/components/ui";
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
  if (!data) return <Loading />;
  const p = data.program;
  const ps = data.path_summary;
  return (
    <>
      <PageHeader crumb={<Link href={`/companies/${data.company.id}`}>{data.company.name}</Link>} title={p.name} lede={p.summary}
        actions={<RunButton kind="deep_research" body={{ company_id: data.company.id }} label={data.company.name} className="btn" onDone={reload}>Research again</RunButton>}>
        <div className="meta">
          <span className={`tag ${p.status === "open" ? "good" : ""}`}>{p.status === "unknown" ? "Status unknown" : label(p.status)}</span>
          <span className="tag brand">Leads to {p.target_family === "se" ? "Sales / Solutions Engineer" : p.target_family === "ae" ? "Account Executive" : "several tracks"}</span>
          {p.typical_open_window && <span className="tag">Usually opens {p.typical_open_window}</span>}
          <span className="tag">{p.confidence.official} of {p.confidence.facts} facts from official sources</span>
        </div>
      </PageHeader>
      {data.concerns.length > 0 && <div style={{ marginBottom: "1rem" }}><Callout tone="warn"><b>Before you apply:</b> {data.concerns.join(" ")}</Callout></div>}
      <div className="grid2">
        {SECTIONS.map(([title, fields]) => {
          const has = fields.some((f) => p.facts?.[f]?.length);
          return has ? <section key={title} className="panel"><h3 style={{ marginBottom: ".6rem" }}>{title}</h3><Facts facts={p.facts} labels={data.field_labels} only={fields} /></section> : null;
        })}
        <section className="panel"><h3 style={{ marginBottom: ".6rem" }}>Where people went next</h3>
          {ps.profiles ? <p className="small">{ps.profiles} profiles: {ps.reached_se} reached SE, {ps.transitions} from sales or technical entry roles{ps.median_months_to_se != null ? `, median ${ps.median_months_to_se} months` : ""}.</p>
            : <p className="small muted">No employee paths yet. Paste public profiles on the company page to build this evidence.</p>}
          {data.career_paths.map((c: any) => <div key={c.id} className="fact small"><b>{c.label}:</b> {c.steps.map((s: any) => s.title).join(", then ")}</div>)}
        </section>
        {data.standout.length > 0 && <section className="panel"><h3 style={{ marginBottom: ".6rem" }}>How to stand out</h3>{data.standout.slice(0, 5).map((s: any, i: number) => <div key={i} className="fact small">{s.action}<div className="muted">{s.why}</div></div>)}</section>}
      </div>
      <div className="sec"><SectionHead title="Open roles in this program" count={data.jobs.length} />
        <JobList jobs={data.jobs} page={10} empty={<div className="empty"><h3>None open right now</h3><p>The Monday scan checks for new postings.</p></div>} /></div>
    </>
  );
}
