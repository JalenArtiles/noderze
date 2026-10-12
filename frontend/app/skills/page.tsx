"use client";
import { Err, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/lib/api";

export default function Skills() {
  const { data, error } = useApi("/api/skills/roadmap");
  return (
    <>
      <PageHeader title="Skills roadmap" lede={`What to learn next, in order, built from the gaps across your best-fit roles${data ? ` (${data.jobs_considered} considered)` : ""}.`}>
        {data?.have?.length > 0 && <div className="meta">{data.have.map((h: string) => <span key={h} className="tag good">{h}</span>)}</div>}
      </PageHeader>
      <Err msg={error} />
      {!data ? <Loading /> : <ol className="route-steps" style={{ maxWidth: 820 }}>
        {data.stages.map((s: any, i: number) => (
          <li key={i} className="done" style={{ paddingBottom: "1.4rem" }}>
            <span className="ic" aria-hidden><b style={{ fontSize: ".75rem" }}>{i + 1}</b></span>
            <section className="panel">
              <div className="spread"><h3>{s.area}</h3>{s.postings > 0 && <span className="tag">{s.postings} roles ask for this</span>}</div>
              <p className="small muted" style={{ margin: ".3rem 0 .6rem" }}>{s.stage}. {s.why}</p>
              {s.resources.map((r: any, j: number) => (
                <div key={j} className="fact small">{r.url ? <a href={r.url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>{r.title}</a> : <b>{r.title}</b>} <span className="faint">{r.provider}, {r.cost}</span><div className="muted">{r.why}</div></div>))}
            </section>
          </li>))}
      </ol>}
    </>
  );
}
