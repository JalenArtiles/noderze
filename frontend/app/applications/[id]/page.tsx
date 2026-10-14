"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Callout, Empty, Err, Loading, PageHeader, RunButton, Tabs } from "@/components/ui";
import { api, day, label, useApi } from "@/lib/api";

export default function ApplicationPage() {
  const { id } = useParams() as { id: string };
  const { data, error, reload } = useApi(`/api/applications/${id}`);
  const [tab, setTab] = useState("ready");
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  if (error) return <Err msg={error} />;
  if (!data) return <Loading />;
  const a = data.application, r = a.readiness || {}, pkg = a.package || {};
  async function patch(body: any) { try { await api(`/api/applications/${id}`, { method: "PATCH", body }); reload(); } catch (e: any) { setErr(e.message); } }
  async function request(action: string) { try { await api(`/api/applications/${id}/request`, { body: { action } }); setErr(null); setNote("Approval requested."); } catch (e: any) { setErr(e.message); } }
  const prepared = !!a.package?.docs || data.docs.length > 0;
  const prepare = <RunButton kind="prepare_application" body={{ job_id: data.job.id }} label={`${a.company}, ${a.title}`} className="btn primary" onDone={reload}>{prepared ? "Regenerate package" : "Prepare the package"}</RunButton>;
  return (
    <>
      <PageHeader crumb={<Link href={`/jobs/${data.job.id}`}>{a.company}</Link>} title={a.title}
        actions={<>{prepared && <div style={{ textAlign: "right", marginRight: ".4rem" }}><div className="score num" style={{ fontFamily: "var(--display)", fontSize: "1.8rem", fontWeight: 800, lineHeight: 1 }}>{r.overall ?? 0}%</div><div className="tiny muted">ready</div></div>}{prepare}</>}>
        <div className="meta"><span className="tag good">{label(a.stage)}</span>{a.deadline && <span className="tag warn">Due {day(a.deadline)}</span>}{a.url && <a className="small" href={a.url} target="_blank" rel="noreferrer">Posting</a>}</div>
      </PageHeader>
      <Err msg={err} />
      {note && <Callout action={<Link href="/approvals">Open approvals</Link>}>{note}</Callout>}
      {!prepared ? (
        <div className="panel"><Empty title="Nothing prepared yet" action={prepare}>Preparing builds a tailored resume for your approval, a cover letter, application answers, outreach drafts, interview prep and a follow-up schedule. Nothing is sent or submitted.</Empty></div>
      ) : <>
      <Tabs tabs={[["ready", "Checklist"], ["resume", "Resume"], ["docs", "Letters and answers"], ["outreach", "Outreach"], ["interview", "Interview prep"], ["log", "Notes and dates"]]} value={tab} onChange={setTab} />
      {tab === "ready" && (
        <div className="grid2">
          <section className="panel"><h3 style={{ marginBottom: ".7rem" }}>Remaining actions</h3>
            {r.checklist?.length ? r.checklist.map((c: any, i: number) => (
              <label key={i} className="fact row small" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                {["study_guide", "standout", "product_walkthrough", "credit", "confirm_details"].includes(c.key) ? <input type="checkbox" onChange={() => patch({ checklist_done: { [c.key]: true } })} /> : <span style={{ width: 13, flex: "none" }} />}<span>{c.text}</span></label>)) : <p className="small muted">All done.</p>}
            <div className="row" style={{ marginTop: "1rem" }}><button className="btn dark sm" onClick={() => request("submit_application")}>Request approval to submit</button></div>
          </section>
          <section className="panel"><h3 style={{ marginBottom: ".7rem" }}>Readiness</h3><div className="bars">{Object.entries(r.components || {}).map(([k, v]: any) => (
            <div key={k} style={{ display: "contents" }}><span>{k}</span><div className="bar"><i style={{ width: `${v}%` }} /></div><span className="num small">{v}%</span></div>))}</div></section>
          {pkg.follow_up_schedule?.length > 0 && <section className="panel"><h3 style={{ marginBottom: ".7rem" }}>Follow-up schedule</h3>{pkg.follow_up_schedule.map((f: any, i: number) => <div key={i} className="fact small"><b>{day(f.when)}</b> {f.what}</div>)}</section>}
          {pkg.standout?.length > 0 && <section className="panel"><h3 style={{ marginBottom: ".7rem" }}>Stand out before applying</h3>{pkg.standout.map((s: any, i: number) => <div key={i} className="fact small">{s.action}<div className="muted">{s.why}</div></div>)}</section>}
        </div>)}
      {tab === "resume" && (data.resume_version ? <div className="panel row" style={{ justifyContent: "space-between" }}><div><h3>{data.resume_version.label}</h3><p className="small muted">{data.resume_version.pending} changes waiting for your decision</p></div><Link className="btn primary" href={`/resume/${data.resume_version.id}`}>Review changes</Link></div> : <div className="panel"><Empty title="No tailored resume yet" action={<Link className="btn" href="/resume">Upload your resume</Link>}>Upload a master resume, then regenerate the package.</Empty></div>)}
      {tab === "docs" && <div className="stack-lg">{data.docs.filter((d: any) => !["interview_prep", "study_guide"].includes(d.kind)).map((d: any) => <Doc key={d.id} d={d} reload={reload} />)}</div>}
      {tab === "outreach" && <div className="stack-lg"><p className="small muted">Approve a message, send it yourself on LinkedIn or by email, then mark it sent. Noderze never sends messages.</p>{data.outreach.map((o: any) => <Out key={o.id} o={o} reload={reload} />)}{!data.outreach.length && <div className="panel"><Empty title="No contacts at this company yet">Find recruiters on the company page, then regenerate the package.</Empty></div>}</div>}
      {tab === "interview" && <Interview data={data} id={id} reload={reload} />}
      {tab === "log" && <section className="panel stack">
        <div className="form"><label className="field">Follow up on<input type="date" defaultValue={a.follow_up_date || ""} onChange={(e) => patch({ follow_up_date: e.target.value })} /></label>
          <label className="field">Deadline<input type="date" defaultValue={a.deadline || ""} onChange={(e) => patch({ deadline: e.target.value })} /></label></div>
        <label className="field">Notes<textarea defaultValue={a.notes || ""} onBlur={(e) => patch({ notes: e.target.value })} placeholder="Saved when you click away" /></label>
        <div>{data.events.map((e: any, i: number) => <div key={i} className="fact small">{day(e.at)}: {e.from ? `${label(e.from)} to ` : ""}{label(e.to)} {e.note || ""}</div>)}</div>
        <div><button className="btn sm" onClick={() => request("reject_opportunity")}>Withdraw (asks for approval)</button></div></section>}
      </>}
    </>
  );
}

function Doc({ d, reload }: any) {
  const [text, setText] = useState(d.content); const [err, setErr] = useState<string | null>(null);
  async function save(status?: string) { try { await api(`/api/docs/${d.id}`, { method: "PATCH", body: status ? { content: text, status } : { content: text } }); reload(); } catch (e: any) { setErr(e.message); } }
  return (<section className="panel stack"><div className="spread"><h3>{d.title}</h3><span className="small muted">{d.generated_by === "llm" ? "Written by Claude" : "Template from your resume facts"}, {d.status}</span></div>
    <textarea value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 180 }} />
    {d.flags?.map((f: string, i: number) => <div key={i} className="small" style={{ color: "var(--amber)" }}>{f}</div>)}
    <Err msg={err} /><div className="row"><button className="btn sm" onClick={() => save()}>Save and recheck</button><button className="btn dark sm" onClick={() => save("approved")}>Approve</button>
      <button className="btn sm" onClick={() => navigator.clipboard.writeText(text)}>Copy</button></div></section>);
}

function Out({ o, reload }: any) {
  const [err, setErr] = useState<string | null>(null);
  async function patch(body: any) { try { await api(`/api/outreach/${o.id}`, { method: "PATCH", body }); reload(); } catch (e: any) { setErr(e.message); } }
  return (<div className="panel"><div className="small muted">{label(o.kind)} to <b>{o.person.name}</b>, {o.person.title}</div><p className="small">{o.reason}</p>
    <div className="msg" style={{ margin: ".5rem 0" }}>{o.message}</div>
    {o.flags?.map((f: string, i: number) => <div key={i} className="small" style={{ color: "var(--amber)" }}>{f}</div>)}<Err msg={err} />
    <div className="row" style={{ marginTop: ".5rem" }}><span className="tag">{label(o.status)}</span>
      {o.status === "draft" && !o.approval_id && <button className="btn dark sm" onClick={() => patch({ request_send: true })}>Request approval</button>}
      {o.status === "approved" && <><button className="btn sm" onClick={() => navigator.clipboard.writeText(o.message)}>Copy</button><button className="btn dark sm" onClick={() => patch({ mark_sent: true })}>Mark sent</button></>}
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
      <button className="btn" onClick={mock} disabled={!q || !ans}>Get feedback</button>{fb && <div className="callout">{fb}</div>}
      <h3>Study guide</h3><pre className="small" style={{ whiteSpace: "pre-wrap", font: "inherit" }}>{data.docs.find((d: any) => d.kind === "study_guide")?.content}</pre></section></div>);
}
