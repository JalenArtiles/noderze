"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Err, Loading, PageHeader, SectionHead } from "@/components/ui";
import Link from "next/link";
import { api, fileUrl, useApi } from "@/lib/api";

const BUCKETS: [string, string, string][] = [["demonstrated", "Already demonstrated", "good"], ["emphasize", "Can reasonably emphasize", "warn"], ["missing", "Missing", ""], ["should_not_claim", "Should not claim", "bad"]];

export default function VersionPage() {
  const { id } = useParams() as { id: string };
  const { data: v, error, reload, setData } = useApi(`/api/resume/versions/${id}`);
  const [err, setErr] = useState<string | null>(null);
  async function decide(eid: string, decision: string, ack = false, after?: string) {
    try { setData(await api(`/api/resume/versions/${id}/edits/${eid}`, { body: { decision, acknowledge_flags: ack, after } })); setErr(null); }
    catch (e: any) { if (e.message.includes("claim-check") && confirm("This edit has claim-check flags. Approve only if every flagged item is true. Approve?")) decide(eid, decision, true, after); else setErr(e.message); }
  }
  async function render() { try { await api(`/api/resume/versions/${id}/render`, { body: {} }); reload(); } catch (e: any) { setErr(e.message); } }
  if (error) return <Err msg={error} />;
  if (!v) return <Loading />;
  const a = v.analysis;
  return (
    <>
      <PageHeader crumb={<Link href="/resume">Resume</Link>} title={v.label} lede="What this role asks for, sorted by what your resume can honestly support, then each proposed change for your decision."
        actions={<>{v.status === "rendered" && <a className="btn" href={fileUrl(`/api/resume/versions/${v.id}/download`)}>Download</a>}<button className="btn primary" onClick={render}>Make the .docx from approved changes</button></>} />
      <div className="grid2">{BUCKETS.map(([k, l, tone]) => (
        <section key={k} className="panel"><div className="row" style={{ marginBottom: ".5rem" }}><span className={`tag ${tone}`}>{a[k].length}</span><h3>{l}</h3></div>
          {a[k].map((x: any, i: number) => <div key={i} className="fact small"><b>{x.area}</b>{x.quote && <div className="muted">"{x.quote}"</div>}{x.guidance && <div className="muted">{x.guidance}</div>}{x.reason && <div className="muted">{x.reason}</div>}</div>)}</section>))}</div>
      {!!a.keywords_to_mirror?.length && <p className="small">Keywords you can mirror because you already demonstrate them: {a.keywords_to_mirror.map((k: any) => k.term).join(", ")}.</p>}
      {!!a.deprioritize?.length && <p className="small muted">Lower priority for this role: {a.deprioritize.map((d: any) => d.text).join("; ")}.</p>}
      <div className="sec"><SectionHead title="Proposed changes" count={v.edits.length} /></div><Err msg={err} />
      {v.edits.map((e: any) => (
        <div key={e.id} className="panel" style={{ marginTop: ".7rem" }}><div className="spread"><b className="small">{e.category === "fix" ? "Fix" : e.category === "rewrite" ? "Rewrite" : "Reorder"}</b><span className={`tag ${e.status === "approved" ? "good" : e.status === "rejected" ? "bad" : "warn"}`}>{e.status === "pending" ? "Waiting for you" : e.status}</span></div>
          <p className="small muted">{e.rationale}</p>
          {e.kind === "replace_text" && <p className="small"><s>{e.find}</s> becomes <b>{e.replace}</b>{e.requires_fact_confirmation && <span className="tag warn" style={{ marginLeft: 6 }}>Confirm this fact is true</span>}</p>}
          {e.kind === "replace_paragraph" && <><p className="small muted"><s>{e.before}</s></p><EditText e={e} onSave={(t: string) => decide(e.id, "approve", false, t)} /></>}
          {e.kind === "reorder" && <ol className="small">{e.preview.map((p: string, i: number) => <li key={i}>{p}</li>)}</ol>}
          {e.flags?.map((f: string, i: number) => <div key={i} className="flag">{f}</div>)}
          <div className="row"><button className="btn dark sm" onClick={() => decide(e.id, "approve")}>Approve</button><button className="btn sm" onClick={() => decide(e.id, "reject")}>Reject</button>
            {e.status !== "pending" && <button className="btn sm" onClick={() => decide(e.id, "reset")}>Undo</button>}</div></div>))}
    </>
  );
}

function EditText({ e, onSave }: any) {
  const [t, setT] = useState(e.after);
  return <div className="stack"><textarea value={t} onChange={(x) => setT(x.target.value)} style={{ minHeight: 70 }} />{t !== e.after && <button className="btn sm" onClick={() => onSave(t)}>Use my wording and approve</button>}</div>;
}
