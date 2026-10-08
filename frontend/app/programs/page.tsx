"use client";
import Link from "next/link";
import { Err } from "@/components/ui";
import { label, useApi } from "@/lib/api";

export default function Programs() {
  const { data, error } = useApi<any[]>("/api/programs");
  const groups: [string, string][] = [["se", "Programs that train you into SE"], ["mixed", "Rotational programs with technical or sales tracks"], ["ae", "Sales academies (path leads to Account Executive)"]];
  return (
    <>
      <h1>Development programs</h1>
      <p className="muted">Academies, associate tracks and rotational programs, with every fact tied to a source. Open one for the full program page.</p>
      <Err msg={error} />
      {groups.map(([g, title]) => {
        const items = data?.filter((p) => p.target_family === g) || [];
        return items.length ? (
          <section key={g}><h2>{title}</h2>
            {items.map((p) => (
              <article key={p.id} className={`card ${g === "se" ? "program" : ""}`}>
                <div className="spread"><div>
                  <div className="small muted">{p.company}{p.watch_status ? `, ${label(p.watch_status)}` : ""}</div>
                  <h3><Link href={`/programs/${p.id}`}>{p.name}</Link></h3>
                  <div className="small">{p.summary}</div>
                  <div className="row small muted" style={{ marginTop: ".35rem" }}>
                    {p.headline["program.duration"] && <span>Duration: {p.headline["program.duration"]}</span>}
                    {p.headline["program.location"] && <span>Where: {p.headline["program.location"]}</span>}
                    {p.headline["comp.base"] && <span>Pay: {p.headline["comp.base"]}</span>}
                  </div>
                </div><span className={`badge ${p.status === "open" ? "good" : ""}`}>{label(p.status)}</span></div>
              </article>))}
          </section>) : null;
      })}
    </>
  );
}
