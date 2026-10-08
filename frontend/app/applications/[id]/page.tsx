"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Err, RunButton, Tabs } from "@/components/ui";
import { api, day, label, useApi } from "@/lib/api";

export default function ApplicationPage() {
  const { id } = useParams() as { id: string };
  const { data, error, reload } = useApi(`/api/applications/${id}`);
  const [tab, setTab] = useState("ready");
  const [err, setErr] = useState<string | null>(null);
  if (error) return <Err msg={error} />;
  if (!data) return <p className="muted">Loading...</p>;
  const a = data.application, r = a.readiness || {}, pkg = a.package || {};
  async function patch(body: any) { try { await api(`/api/applications/${id}`, { method: "PATCH", body }); reload(); } catch (e: any) { setErr(e.message); } }
  async function request(action: string) { try { await api(`/api/applications/${id}/request`, { body: { action } }); setErr(null); alert("Approval requested. Decide on the Approvals page."); } catch (e: any) { setErr(e.message); } }
  return (
    <>
      <div className="small"><Link href={`/jobs/${data.job.id}`}>{a.company}</Link></div>
      <div className="spread"><div><h1>{a.title}</h1><div className="row small"><span className="badge good">{label(a.stage)}</span>{a.deadline && <span>Due {day(a.deadline)}</span>}{a.url && <a href={a.url} target="_blank" rel="noreferrer">Posting</a>}</div></div>
        <div style={{ textAlign: "right" }}><div className="score num">{r.overall ?? "-"}<small>%</small></div><div className="small muted">Application readiness</div></div></div>
      <Err msg={err} />
      <Tabs tabs={[["ready", "Prepare me"], ["resume", "Resume"], ["docs", "Letters and answers"], ["outreach", "Outreach"], ["interview", "Interview prep"], ["log", "Tracker"]]} value={tab} onChange={setTab} />
      {tab === "ready" && (
        <div className="grid2">
          <section className="panel"><h3>Readiness</h3><div className="bars">{Object.entries(r.components || {}).map(([k, v]: any) => (
            <div key={k} style={{ display: "contents" }}><span>{k}</span><div className="bar"><i style={{ width: `${v}%` }} /></div><span className="num">{v}%</span></div>))}</div></section>
          <section className="panel"><h3>Remaining actions</h3>
            {r.checklist?.map((c: any, i: number) => (
              <label key={i} className="fact row small" style={{ alignItems: "flex-start" }}>
                {["study_guide", "standout", "product_walkthrough"].includes(c.key) ? <input type="checkbox" onChange={() => patch({ checklist_done: { [c.key]: true } })} /> : <span style={{ width: 13 }} />}<span>{c.text}</span></label>))}
            <div className="row" style={{ marginTop: ".8rem" }}><RunButton kind="prepare_application" body={{ job_id: data.job.id }} className="btn secondary small" onDone={reload}>Regenerate package</RunButton>
              <button className="btn primary small" onClick={() => request("submit_application")}>Request approval to submit</button></div>
            <p className="small muted">To fill the form in a browser: <code>python -m app.automation.runner --application-id {a.id}</code>. It pauses at CAPTCHAs and logins, and waits for your approval before clicking submit.</p>
          </section>
          <section className="panel"><h3>Follow-up schedule</h3>{pkg.follow_up_schedule?.map((f: any, i: number) => <div key={i} className="fact small"><b>{day(f.when)}</b> {f.what}</div>)}</section>
          <section className="panel"><h3>Stand out before applying</h3>{pkg.standout?.map((s: any, i: number) => <div key={i} className="fact small">{s.action}<div className="muted">{s.why}</div></div>)}</section>
        </div>)}
      {tab === "resume" && (data.resume_version ? <p><Link className="btn" href={`/resume/${data.resume_version.id}`}>Review {data.resume_version.pending} pending resume edits</Link> <span className="small muted">Version: {data.resume_version.label}</span></p> : <p className="muted">Upload a master resume, then regenerate the package.</p>)}
      {tab === "docs" && data.docs.filter((d: any) => !["interview_prep", "study_guide"].includes(d.kind)).map((d: any) => <Doc key={d.id} d={d} reload={reload} />)}
      {tab === "outreach" && <><p className="small muted">Approve a message, send it yourself on LinkedIn or by email, then mark it sent. The app never sends messages on its own.</p>{data.outreach.map((o: any) => <Out key={o.id} o={o} reload={reload} />)}{!data.outreach.length && <p className="muted">No contacts at this company yet. Find recruiters on the company page, then regenerate.</p>}</>}
      {tab === "interview" && <Interview data={data} id={id} reload={reload} />}
      {tab === "log" && <section className="panel">{data.events.map((e: any, i: number) => <div key={i} className="fact small">{day(e.at)}: {e.from ? `${label(e.from)} to ` : ""}{label(e.to)} {e.note || ""}</div>)}
        <h3 style={{ marginTop: "1rem" }}>Notes</h3><textarea defaultValue={a.notes || ""} onBlur={(e) => patch({ notes: e.target.value })} />
        <div className="row small" style={{ marginTop: ".5rem" }}><label>Follow up on <input type="date" defaultValue={a.follow_up_date || ""} onChange={(e) => patch({ follow_up_date: e.target.value })} /></label>
          <label>Deadline <input type="date" defaultValue={a.deadline || ""} onChange={(e) => patch({ deadline: e.target.value })} /></label>
          <button className="btn secondary small" onClick={() => request("reject_opportunity")}>Withdraw (needs approval)</button></div></section>}
    </>
  );
}

function Doc({ d, reload }: any) {
  const [text, setText] = useState(d.content); const [err, setErr] = useState<string | null>(null);
  async function save(status?: string) { try { await api(`/api/docs/${d.id}`, { method: "PATCH", body: status ? { content: text, status } : { content: text } }); reload(); } catch (e: any) { setErr(e.message); } }
  return (<section className="panel stack"><div className="spread"><h3>{d.title}</h3><span className="small muted">{d.generated_by === "llm" ? "Written by Claude" : "Template from your resume facts"}, {d.status}</span></div>
    <textarea value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 180 }} />
    {d.flags?.map((f: string, i: number) => <div key={i} className="small" style={{ color: "var(--warn)" }}>{f}</div>)}
    <Err msg={err} /><div className="row"><button className="btn secondary small" onClick={() => save()}>Save and recheck</button><button className="btn small" onClick={() => save("approved")}>Approve</button>
      <button className="btn secondary small" onClick={() => navigator.clipboard.writeText(text)}>Copy</button></div></section>);
}

function Out({ o, reload }: any) {
  const [err, setErr] = useState<string | null>(null);
  async function patch(body: any) { try { await api(`/api/outreach/${o.id}`, { method: "PATCH", body }); reload(); } catch (e: any) { setErr(e.message); } }
  return (<div className="card"><div className="small muted">{label(o.kind)} to <b>{o.person.name}</b>, {o.person.title}</div><p className="small">{o.reason}</p>
    <blockquote style={{ borderLeft: "3px solid var(--maroon)", margin: 0, paddingLeft: ".7rem" }}>{o.message}</blockquote>
    {o.flags?.map((f: string, i: number) => <div key={i} className="small" style={{ color: "var(--warn)" }}>{f}</div>)}<Err msg={err} />
    <div className="row" style={{ marginTop: ".5rem" }}><span className="badge">{o.status}</span>
      {o.status === "draft" && !o.approval_id && <button className="btn small" onClick={() => patch({ request_send: true })}>Request approval</button>}
      {o.status === "approved" && <><button className="btn secondary small" onClick={() => navigator.clipboard.writeText(o.message)}>Copy</button><button className="btn small" onClick={() => patch({ mark_sent: true })}>Mark sent</button></>}
      {o.status === "sent" && <input placeholder="Log their reply" onBlur={(e) => e.target.value && patch({ response: e.target.value })} />}</div></div>);
}

function Interview({ data, id, reload }: any) {
  const qs = data.application.package?.interview_questions || {};
  const [q, setQ] = useState(""); const [ans, setAns] = useState(""); const [fb, setFb] = useState<string | null>(null);
  async function mock() { const r = await api(`/api/applications/${id}/mock`, { body: { question: q, answer: ans } }); setFb(r.feedback); reload(); }
  return (<div className="grid2"><section className="panel">{Object.entries(qs).map(([k, list]: any) => (<div key={k}><h3 style={{ marginTop: ".6rem" }}>{label(k)}</h3>
    {list.map((x: string, i: number) => <div key={i} className="fact small"><button style={{ all: "unset", cursor: "pointer" }} onClick={() => { setQ(x); setFb(null); }}>{x}</button></div>)}</div>))}</section>
    <section className="panel stack"><h3>Mock interview</h3><p className="small muted">Pick a question, answer it as you would out loud, and get feedback. Practiced questions raise your readiness score.</p>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Question" /><textarea value={ans} onChange={(e) => setAns(e.target.value)} placeholder="Your answer" />
      <button className="btn" onClick={mock} disabled={!q || !ans}>Get feedback</button>{fb && <div className="notice">{fb}</div>}
      <h3>Study guide</h3><pre className="small" style={{ whiteSpace: "pre-wrap", font: "inherit" }}>{data.docs.find((d: any) => d.kind === "study_guide")?.content}</pre></section></div>);
}
