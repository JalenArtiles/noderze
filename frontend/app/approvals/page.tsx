"use client";
import { useState } from "react";
import { Empty, Err, Loading, PageHeader, SectionHead } from "@/components/ui";
import { api, day, label, useApi } from "@/lib/api";

export default function Approvals() {
  const { data, error, reload } = useApi<any[]>("/api/approvals");
  const [err, setErr] = useState<string | null>(null);
  async function decide(id: number, approve: boolean) { try { await api(`/api/approvals/${id}/decide`, { body: { approve } }); reload(); } catch (e: any) { setErr(e.message); } }
  const pending = data?.filter((a) => a.status === "pending") || [];
  const done = data?.filter((a) => a.status !== "pending") || [];
  return (
    <>
      <PageHeader title="Approvals" lede="Submitting applications, sending messages, changing resume facts and claiming qualifications all wait here. Nothing leaves your computer without a yes." />
      <Err msg={error || err} />
      {!data ? <Loading /> : <>
        <SectionHead title="Waiting for you" count={pending.length} />
        {pending.length ? <div className="list">{pending.map((a) => (
          <div key={a.id} className="li" style={{ alignItems: "flex-start" }}>
            <div className="grow"><div className="title">{a.label}</div><div className="sub">{a.summary}</div>
              {a.payload?.message && <div className="msg" style={{ marginTop: ".5rem" }}>{a.payload.message}</div>}
              {a.payload?.unverified_claims > 0 && <div className="flag">{a.payload.unverified_claims} approved resume change(s) carry claim-check flags. Re-read them first.</div>}
              <div className="tiny faint" style={{ marginTop: ".3rem" }}>Requested {day(a.created_at)}</div></div>
            <div className="end"><button className="btn sm" onClick={() => decide(a.id, false)}>Reject</button><button className="btn primary sm" onClick={() => decide(a.id, true)}>Approve</button></div>
          </div>))}</div>
          : <div className="panel"><Empty title="Nothing waiting">When you ask Noderze to submit or send something, it shows up here first.</Empty></div>}
        {done.length > 0 && <div className="sec"><SectionHead title="History" count={done.length} />
          <div className="list">{done.map((a) => (
            <div key={a.id} className="li compact"><div className="grow small">{a.summary}<div className="tiny faint">{day(a.created_at)}{a.result?.next || a.result?.error ? `. ${a.result?.next || a.result?.error}` : ""}</div></div>
              <span className={`tag ${a.status === "rejected" || a.status === "failed" ? "bad" : "good"}`}>{label(a.status)}</span></div>))}</div></div>}
      </>}
    </>
  );
}
