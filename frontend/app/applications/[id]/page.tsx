"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Copy, Download, Mail, RotateCcw, Trash2 } from "lucide-react";
import { Callout, Empty, Err, Loading, PageHeader, RunButton, Tabs, stageLabel, useTab } from "@/components/ui";
import { api, day, fileUrl, label, useApi } from "@/lib/api";

export default function ApplicationPage() {
  const { id } = useParams() as { id: string };
  const { data, error, reload } = useApi(`/api/applications/${id}`);
  const [tab, setTab] = useTab("ready");
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  if (error) return <Err msg={error} />;
  if (!data) return <Loading />;
  const a = data.application, r = a.readiness || {}, pkg = a.package || {};
  async function patch(body: any) { try { await api(`/api/applications/${id}`, { method: "PATCH", body }); reload(); } catch (e: any) { setErr(e.message); } }
  async function request(action: string) { try { await api(`/api/applications/${id}/request`, { body: { action } }); setErr(null); setNote("Approval requested."); } catch (e: any) { setErr(e.message); } }
  const prepared = !!a.package?.docs || data.docs.length > 0;
  const prepare = <RunButton kind="prepare_application" body={{ job_id: data.job.id }} label={`${a.company}, ${a.title}`} className="btn primary" onDone={reload}>{prepared ? "Regenerate package" : "Prepare the package"}</RunButton>;
  const letters = data.docs.filter((d: any) => d.kind === "cover_letter");
  const unread = (data.replies || []).filter((x: any) => !x.seen).length;
  return (
    <>
      <PageHeader crumb={<Link href={`/jobs/${data.job.id}`}>{a.company}</Link>} title={a.title}
        actions={<>{prepared && <div style={{ textAlign: "right", marginRight: ".4rem" }}><div className="score num" style={{ fontFamily: "var(--display)", fontSize: "1.8rem", fontWeight: 800, lineHeight: 1 }}>{r.overall ?? 0}%</div><div className="tiny muted">ready</div></div>}{prepare}</>}>
        <div className="meta">
          <select className="stage-pick" value={a.stage} onChange={(e) => patch({ stage: e.target.value })} aria-label="Stage">
            {data.stages_all?.map((x: string) => <option key={x} value={x}>{stageLabel(x)}</option>) || <option value={a.stage}>{stageLabel(a.stage)}</option>}</select>
          {a.is_intern ? <span className="tag track network">Spring internship</span> : <span className="tag">Career role</span>}
          {a.date_applied && <span className="tag good">Applied {day(a.date_applied)}</span>}
          {a.deadline && <span className="tag warn">Due {day(a.deadline)}</span>}
          {unread > 0 && <Link href="/replies" className="tag new"><Mail size={12} />{unread} new {unread === 1 ? "email" : "emails"}</Link>}
          <Link className="small" href={`/apply/${data.job.id}`}>Tailored resume and apply</Link>
          {a.url && <a className="small" href={a.url} target="_blank" rel="noreferrer">Posting</a>}</div>
      </PageHeader>
      <Err msg={err} />
      {note && <Callout action={<Link href="/approvals">Open approvals</Link>}>{note}</Callout>}
      <Tabs tabs={[["ready", "Checklist"], ["docs", "Cover letter and questions", (data.questions || []).length || null], ["resume", "Resume"], ["outreach", "Outreach"], ["interview", "Interview prep"], ["log", "Notes and dates"]]} value={tab} onChange={setTab} />
      {tab === "ready" && (!prepared ? (
        <div className="panel"><Empty title="Nothing prepared yet" action={prepare}>Preparing builds a tailored resume for your approval, a cover letter, outreach drafts, interview prep and a follow-up schedule. Nothing is sent or submitted.</Empty></div>
      ) : (
        <div className="grid2">
          {data.replies?.length > 0 && <section className="panel" style={{ gridColumn: "1 / -1" }}><h3 style={{ marginBottom: ".6rem" }}>Emails from {a.company}</h3>
            {data.replies.slice(0, 4).map((m: any) => <ReplyLine key={m.id} m={m} />)}</section>}
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
        </div>))}
      {tab === "resume" && (data.resume_version ? <div className="panel row" style={{ justifyContent: "space-between" }}><div><h3>{data.resume_version.label}</h3><p className="small muted">{data.resume_version.pending} changes waiting for your decision</p></div><Link className="btn primary" href={`/resume/${data.resume_version.id}`}>Review changes</Link></div> : <div className="panel"><Empty title="No tailored resume yet" action={<Link className="btn" href={`/apply/${data.job.id}`}>Tailor it in Apply</Link>}>Open Apply for this role to tailor your resume to its keywords.</Empty></div>)}
      {tab === "docs" && <div className="stack-lg">
        {letters.length ? letters.map((d: any) => <Doc key={d.id} d={d} reload={reload} />) :
          <div className="panel"><Empty title="No cover letter yet" action={prepare}>Prepare the package to write one in your cover letter style. You can edit it here and download it as a Word file.</Empty></div>}
        <Questions appId={id} items={data.questions || []} llm={data.llm} reload={reload} />
      </div>}
      {tab === "outreach" && <div className="stack-lg"><p className="small muted">Approve a message, send it yourself on LinkedIn or by email, then mark it sent. Noderze never sends messages.</p>{data.outreach.map((o: any) => <Out key={o.id} o={o} reload={reload} />)}{!data.outreach.length && <div className="panel"><Empty title="No contacts at this company yet">Find recruiters on the company page, then regenerate the package.</Empty></div>}</div>}
      {tab === "interview" && <Interview data={data} id={id} reload={reload} />}
      {tab === "log" && <section className="panel stack">
        <div className="form"><label className="field">Follow up on<input type="date" defaultValue={a.follow_up_date || ""} onChange={(e) => patch({ follow_up_date: e.target.value })} /></label>
          <label className="field">Deadline<input type="date" defaultValue={a.deadline || ""} onChange={(e) => patch({ deadline: e.target.value })} /></label></div>
        <label className="field">Notes<textarea defaultValue={a.notes || ""} onBlur={(e) => patch({ notes: e.target.value })} placeholder="Saved when you click away" /></label>
        <div>{data.events.map((e: any, i: number) => <div key={i} className="fact small">{day(e.at)}: {e.from ? `${stageLabel(e.from)} to ` : ""}{stageLabel(e.to)} {e.note || ""}</div>)}</div>
        <div><button className="btn sm" onClick={() => request("reject_opportunity")}>Withdraw (asks for approval)</button></div></section>}
    </>
  );
}

function Doc({ d, reload }: any) {
  const [text, setText] = useState(d.content); const [err, setErr] = useState<string | null>(null); const [ok, setOk] = useState<string | null>(null);
  async function save(status?: string) { try { await api(`/api/docs/${d.id}`, { method: "PATCH", body: status ? { content: text, status } : { content: text } }); setOk(status ? "Approved." : "Saved."); reload(); } catch (e: any) { setErr(e.message); } }
  return (<section className="panel stack"><div className="spread"><h3>{d.kind === "cover_letter" ? "Cover letter" : d.title}</h3><span className="small muted">{d.generated_by === "llm" ? "Written by Claude" : "Written from your resume"}, {d.status === "approved" ? "approved" : "draft"}</span></div>
    <textarea value={text} onChange={(e) => { setText(e.target.value); setOk(null); }} style={{ minHeight: d.kind === "cover_letter" ? 420 : 180 }} />
    {d.flags?.map((f: string, i: number) => <div key={i} className="small" style={{ color: "var(--amber)" }}>{f}</div>)}
    <Err msg={err} /><div className="row"><button className="btn sm" onClick={() => save()}>Save and recheck</button><button className="btn dark sm" onClick={() => save("approved")}>Approve</button>
      <CopyButton text={text} />
      {d.kind === "cover_letter" && <a className="btn sm" href={fileUrl(`/api/docs/${d.id}/docx`)} title="Save your changes first, then download"><Download />Download Word file</a>}
      {ok && <span className="small muted">{ok}</span>}</div></section>);
}

function CopyButton({ text, label: lab = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return <button className="btn sm" onClick={() => { navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}><Copy />{done ? "Copied" : lab}</button>;
}

/** Paste a question from the application, get an answer written in your voice, then edit, copy or rewrite it. */
function Questions({ appId, items, llm, reload }: { appId: string; items: any[]; llm: boolean; reload: () => void }) {
  const empty = { question: "", notes: "", limit: "", unit: "words" };
  const [f, setF] = useState<any>(empty);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function add() {
    setBusy(true); setErr(null);
    const n = parseInt(f.limit, 10) || null;
    try {
      await api(`/api/applications/${appId}/questions`, { body: { question: f.question, notes: f.notes || null,
        limit_words: f.unit === "words" ? n : null, limit_chars: f.unit === "characters" ? n : null } });
      setF(empty); reload();
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  return (
    <section className="panel stack" id="questions">
      <div className="spread"><h3>Application questions</h3>{items.length > 0 && <span className="small muted">{items.length} answered</span>}</div>
      <p className="small muted">Paste a question from the application and Noderze writes an answer in your voice: why this company, your soft skills, and a quick line of experience. Edit it, copy it, or have it rewritten.</p>
      {!llm && <Callout action={<Link href="/settings#connections">Add your key</Link>}>Answers come from templates until you add your Anthropic API key. With it, Claude writes each answer for the exact question.</Callout>}
      <textarea value={f.question} onChange={(e) => setF({ ...f, question: e.target.value })} placeholder="Paste the question, e.g. Why would you like to work at FOX?" style={{ minHeight: 80 }} />
      <div className="form q-opts">
        <label className="field">Anything to lean on? (optional)<input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="e.g. mention the AE internship and that I adapt under pressure" /></label>
        <label className="field">Length limit (optional)<span className="row" style={{ gap: ".4rem", flexWrap: "nowrap" }}>
          <input type="number" min={1} value={f.limit} onChange={(e) => setF({ ...f, limit: e.target.value })} placeholder="None" style={{ width: 110 }} />
          <select value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })}><option>words</option><option>characters</option></select></span></label>
      </div>
      <Err msg={err} />
      <div className="row"><button className="btn primary" onClick={add} disabled={busy || !f.question.trim()}>{busy ? "Writing" : "Write an answer"}</button></div>
      {items.map((q) => <QA key={q.id} q={q} reload={reload} />)}
    </section>
  );
}

function QA({ q, reload }: { q: any; reload: () => void }) {
  const [text, setText] = useState(q.answer);
  const [notes, setNotes] = useState(q.notes || "");
  const [busy, setBusy] = useState<string | null>(null);
  const [redo, setRedo] = useState(false);
  useEffect(() => setText(q.answer), [q.answer]);
  async function patch(body: any, what: string) {
    setBusy(what);
    try { await api(`/api/questions/${q.id}`, { method: "PATCH", body }); setRedo(false); reload(); } catch {}
    setBusy(null);
  }
  async function del() { if (!confirm("Delete this question and its answer?")) return; await api(`/api/questions/${q.id}`, { method: "DELETE" }); reload(); }
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const limit = q.limit_words ? `${words} of ${q.limit_words} words` : q.limit_chars ? `${text.length} of ${q.limit_chars} characters` : `${words} words, ${text.length} characters`;
  return (
    <div className="qa">
      <div className="q">{q.question}</div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: Math.min(520, Math.max(170, 60 + Math.ceil(text.length / 120) * 24)) }} />
      {q.flags?.map((x: string, i: number) => <div key={i} className="small" style={{ color: "var(--amber)" }}>{x}</div>)}
      <div className="row">
        <CopyButton text={text} />
        {text !== q.answer && <button className="btn sm dark" disabled={!!busy} onClick={() => patch({ answer: text }, "save")}>{busy === "save" ? "Saving" : "Save edits"}</button>}
        <button className="btn sm" disabled={!!busy} onClick={() => setRedo(!redo)}><RotateCcw />Write it again</button>
        <button className="btn sm quiet" onClick={del}><Trash2 />Delete</button>
        <span className="tiny muted" style={{ marginLeft: "auto" }}>{limit} · {q.generated_by === "llm" ? "Claude" : q.generated_by === "you" ? "Your edits" : "Template"}</span>
      </div>
      {redo && <div className="row" style={{ flexWrap: "nowrap" }}>
        <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="What should change? e.g. shorter, more human, mention teamwork" style={{ flex: 1 }} />
        <button className="btn sm primary" disabled={!!busy} onClick={() => patch({ regenerate: true, notes }, "redo")}>{busy === "redo" ? "Writing" : "Rewrite"}</button></div>}
    </div>
  );
}

function ReplyLine({ m }: { m: any }) {
  return (
    <div className={`fact small reply-line ${m.seen ? "" : "unread"}`}>
      <span className={`tag ${m.kind === "rejection" ? "bad" : m.kind === "confirmation" ? "" : "good"}`}>{m.kind_label}</span>
      <b>{m.subject}</b> <span className="muted">{m.received_at ? day(m.received_at) : ""}</span>
      {m.url && <a href={m.url} target="_blank" rel="noreferrer" style={{ marginLeft: ".4rem" }}>Open in Gmail</a>}
    </div>
  );
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
