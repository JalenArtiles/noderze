"use client";
import { useState } from "react";
import { Err } from "@/components/ui";
import { api, day, useApi } from "@/lib/api";

export default function Approvals() {
  const { data, error, reload } = useApi<any[]>("/api/approvals");
  const [err, setErr] = useState<string | null>(null);
  async function decide(id: number, approve: boolean) { try { await api(`/api/approvals/${id}/decide`, { body: { approve } }); reload(); } catch (e: any) { setErr(e.message); } }
  const pending = data?.filter((a) => a.status === "pending") || [];
  return (
    <>
      <h1>Approvals</h1>
      <p className="muted">Submitting applications, sending messages, changing resume facts and claiming qualifications all wait here for you. Nothing external happens without a yes.</p>
      <Err msg={error || err} />
      <h2>Waiting for you ({pending.length})</h2>
      {pending.map((a) => (
        <div key={a.id} className="card"><div className="spread"><div><b>{a.label}</b><div>{a.summary}</div>
          {a.payload?.message && <blockquote className="small" style={{ borderLeft: "3px solid var(--rule)", margin: ".4rem 0", paddingLeft: ".6rem" }}>{a.payload.message}</blockquote>}
          {a.payload?.unverified_claims > 0 && <div className="error small">{a.payload.unverified_claims} approved resume edit(s) carry claim-check flags. Re-read them first.</div>}
          {a.payload?.screenshot && <div className="small muted">Screenshot saved at {a.payload.screenshot}</div>}
          <div className="small muted">Requested {day(a.created_at)}</div></div>
          <div className="row"><button className="btn primary" onClick={() => decide(a.id, true)}>Approve</button><button className="btn secondary" onClick={() => decide(a.id, false)}>Reject</button></div></div></div>))}
      {!pending.length && <p className="muted">Nothing waiting.</p>}
      <h2>History</h2>
      <table><tbody>{data?.filter((a) => a.status !== "pending").map((a) => (
        <tr key={a.id}><td>{a.summary}</td><td><span className={`badge ${a.status === "rejected" || a.status === "failed" ? "bad" : "good"}`}>{a.status}</span></td><td className="small muted">{day(a.created_at)}</td><td className="small muted">{a.result?.next || a.result?.error || ""}</td></tr>))}</tbody></table>
    </>
  );
}
