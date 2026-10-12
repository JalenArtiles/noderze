"use client";
import Link from "next/link";
import { Err, Loading, PageHeader, SectionHead } from "@/components/ui";
import { CompanyLogo } from "@/components/visual";
import { label, useApi } from "@/lib/api";

const GROUPS: [string, string, string][] = [
  ["se", "Programs that train you into SE", "Associate SE roles and academies that end in a sales or solutions engineering job."],
  ["mixed", "Rotational programs", "Several tracks, some technical or sales."],
  ["ae", "Sales academies", "These lead to Account Executive. SE is possible later but not the stated path."]];

export default function Programs() {
  const { data, error } = useApi<any[]>("/api/programs");
  return (
    <>
      <PageHeader title="ASE and SE programs" lede="Academies, associate tracks and rotational programs. Every fact links to its source." />
      <Err msg={error} />
      {!data ? <Loading /> : GROUPS.map(([g, title, hint]) => {
        const items = data.filter((p) => p.target_family === g);
        return items.length ? (
          <div key={g} className="sec" style={{ marginTop: g === "se" ? 0 : undefined }}>
            <SectionHead title={title} count={items.length} aside={<span className="muted">{hint}</span>} />
            <div className="list">{items.map((p) => (
              <Link key={p.id} href={`/programs/${p.id}`} className="li" style={{ alignItems: "flex-start" }}>
                <CompanyLogo name={p.company} website={p.company_website} size="sm" />
                <div className="grow">
                  <div className="title">{p.name}</div>
                  <div className="sub">{p.company}</div>
                  <div className="meta">
                    {p.headline["program.duration"] && <span className="tag">{p.headline["program.duration"]}</span>}
                    {p.headline["program.location"] && <span className="tag">{p.headline["program.location"]}</span>}
                    {p.headline["comp.base"] && <span className="tag">{p.headline["comp.base"]}</span>}
                  </div>
                </div>
                <span className={`tag ${p.status === "open" ? "good" : ""}`}>{p.status === "unknown" ? "Status unknown" : label(p.status)}</span>
              </Link>))}</div>
          </div>) : null;
      })}
    </>
  );
}
