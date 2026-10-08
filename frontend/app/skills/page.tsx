"use client";
import { Err } from "@/components/ui";
import { useApi } from "@/lib/api";

export default function Skills() {
  const { data, error } = useApi("/api/skills/roadmap");
  return (
    <>
      <h1>Skills roadmap</h1>
      <p className="muted">Built from the gaps across your higher-fit opportunities ({data?.jobs_considered ?? 0} considered). Each step says why it makes you more useful as an SE.</p>
      <Err msg={error} />
      {data && <p className="small">You already cover: {data.have.join(", ")}.</p>}
      <ol style={{ paddingLeft: "1.1rem" }}>
        {data?.stages.map((s: any, i: number) => (
          <li key={i} className="panel" style={{ marginBottom: ".7rem" }}>
            <div className="spread"><h3>{s.stage}: {s.area}</h3>{s.postings > 0 && <span className="small muted">{s.postings} posting(s) ask for this</span>}</div>
            <p className="small">{s.why}</p>
            {s.resources.map((r: any, j: number) => (
              <div key={j} className="fact small">{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> : <b>{r.title}</b>} <span className="muted">({r.provider}, {r.cost})</span><div className="muted">{r.why}</div></div>))}
          </li>))}
      </ol>
    </>
  );
}
