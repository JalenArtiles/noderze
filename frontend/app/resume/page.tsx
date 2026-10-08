"use client";
import Link from "next/link";
import { useState } from "react";
import { Err } from "@/components/ui";
import { api, day, useApi } from "@/lib/api";

export default function ResumePage() {
  const { data, error, reload } = useApi("/api/resume");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function upload(f: File) { setBusy(true); const form = new FormData(); form.append("file", f);
    try { await api("/api/resume/upload", { form }); setErr(null); reload(); } catch (e: any) { setErr(e.message); } setBusy(false); }
  const m = data?.master;
  const sev: Record<string, string> = { high: "bad", medium: "warn", low: "" };
  return (
    <>
      <h1>Resume</h1>
      <p className="muted">Upload your master resume once. Every tailored version starts from it, and every suggested change must trace back to something it or your profile already says.</p>
      <div className="row"><label className="btn">{busy ? "Reading..." : m ? "Replace master resume (.docx)" : "Upload master resume (.docx)"}
        <input type="file" accept=".docx" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>{m && <span className="small muted">{m.filename}, uploaded {day(m.uploaded_at)}, {m.ledger.length} facts</span>}</div>
      <Err msg={error || err} />
      {m && (<>
        <h2>Checks on your master resume</h2>
        {m.checks.map((c: any, i: number) => <div key={i} className="fact"><span className={`badge ${sev[c.severity]}`}>{c.severity}</span> {c.message}</div>)}
        <p className="small muted">Fixes for dates, typos and overclaims are proposed as edits in every tailored version, so you approve them once per version.</p>
        <h2>Fact ledger</h2><p className="small muted">The only material the engine may draw on when it writes about you.</p>
        <table><tbody>{m.ledger.filter((f: any) => f.kind !== "role").map((f: any) => <tr key={f.id}><td className="small muted">{f.id}</td><td className="small">{f.text}</td></tr>)}</tbody></table>
      </>)}
      <h2>Tailored versions</h2>
      <table><thead><tr><th>Version</th><th>Pending edits</th><th>Status</th><th>Used by</th></tr></thead><tbody>
        {data?.versions.map((v: any) => <tr key={v.id}><td><Link href={`/resume/${v.id}`}>{v.label}</Link></td><td className="num">{v.pending}</td><td>{v.status}</td><td>{v.used_by_application ? <Link href={`/applications/${v.used_by_application}`}>Application</Link> : ""}</td></tr>)}
      </tbody></table>
      {!data?.versions.length && <p className="muted small">Versions appear when you tailor for a job (Prepare application, or Tailor on a job page).</p>}
    </>
  );
}
