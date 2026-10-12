"use client";
import Link from "next/link";
import { useState } from "react";
import { Upload } from "lucide-react";
import { Empty, Err, Loading, PageHeader, SectionHead } from "@/components/ui";
import { api, day, useApi } from "@/lib/api";

const SEV: [string, string, string][] = [["high", "Fix before you apply", "bad"], ["medium", "Worth fixing", "warn"], ["low", "Optional", ""]];

export default function ResumePage() {
  const { data, error, reload } = useApi("/api/resume");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function upload(f: File) { setBusy(true); const form = new FormData(); form.append("file", f);
    try { await api("/api/resume/upload", { form }); setErr(null); reload(); } catch (e: any) { setErr(e.message); } setBusy(false); }
  const m = data?.master;
  const picker = (
    <label className={`btn ${m ? "" : "primary"}`}><Upload />{busy ? "Reading your resume..." : m ? "Replace resume" : "Upload your resume (.docx)"}
      <input type="file" accept=".docx" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>);
  return (
    <>
      <PageHeader title="Resume" lede="Your master resume. Every tailored version starts from it, and every suggested change must trace back to something it or your profile already says."
        actions={m ? picker : null}>
        {m && <p className="small muted" style={{ marginTop: ".5rem" }}>{m.filename}, uploaded {day(m.uploaded_at)}. {m.ledger.length} facts on file.</p>}
      </PageHeader>
      <Err msg={error || err} />
      {!data ? <Loading /> : !m ? <div className="panel"><Empty title="Upload your resume to start" action={picker}>Word format (.docx) keeps your formatting when Noderze makes tailored versions.</Empty></div> : <>
        <div className="grid2">
          {SEV.map(([sev, title, tone]) => {
            const items = m.checks.filter((c: any) => c.severity === sev);
            if (!items.length) return null;
            const body = items.map((c: any, i: number) => <div key={i} className="fact small">{c.message}</div>);
            return (
              <section key={sev} className="panel">
                <div className="row" style={{ marginBottom: ".6rem" }}><span className={`tag ${tone}`}>{items.length}</span><h3>{title}</h3></div>
                {sev === "low" && items.length > 3 ? <>{body.slice(0, 3)}<details className="more-info" style={{ marginTop: ".5rem" }}><summary>{items.length - 3} more</summary>{body.slice(3)}</details></> : body}
              </section>);
          })}
        </div>
        <p className="small faint" style={{ marginTop: ".7rem" }}>Fixes for dates, typos and overclaims are offered as changes in every tailored version, so you approve them once per version.</p>

        <div className="sec">
          <SectionHead title="Tailored versions" count={latestPerRole(data.versions).length} />
          {data.versions.length ? <div className="list">{latestPerRole(data.versions).map(({ v, older }: any) => (
            <Link key={v.id} href={`/resume/${v.id}`} className="li">
              <div className="grow"><div className="title">{v.label}</div><div className="sub">{v.used_by_application ? "Used by an application" : "Not attached to an application"}{older ? `. ${older} older ${older === 1 ? "version" : "versions"} hidden` : ""}</div></div>
              {v.pending > 0 ? <span className="tag warn">{v.pending} to review</span> : <span className="tag good">{v.status === "rendered" ? "Ready to download" : "Reviewed"}</span>}
            </Link>))}</div>
            : <div className="panel"><Empty title="No tailored versions yet">Click Apply on any role and Noderze makes one for that company.</Empty></div>}
        </div>

        <div className="sec">
          <details className="panel more-info"><summary>What Noderze knows from your resume ({m.ledger.filter((f: any) => f.kind !== "role").length} facts)</summary>
            <p className="small muted" style={{ marginBottom: ".6rem" }}>The only material Noderze may draw on when it writes about you.</p>
            <table><tbody>{m.ledger.filter((f: any) => f.kind !== "role").map((f: any) => <tr key={f.id}><td className="small faint" style={{ width: 120 }}>{f.id}</td><td className="small">{f.text}</td></tr>)}</tbody></table>
          </details>
        </div>
      </>}
    </>
  );
}

/** Clicking Apply again makes a fresh version; show the newest per role and count the rest. */
function latestPerRole(versions: any[]) {
  const seen = new Map<string, { v: any; older: number }>();
  [...versions].sort((a, b) => b.id - a.id).forEach((v) => { const e = seen.get(v.label); if (e) e.older += 1; else seen.set(v.label, { v, older: 0 }); });
  return Array.from(seen.values());
}
