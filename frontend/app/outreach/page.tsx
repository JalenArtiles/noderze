"use client";
import { useState } from "react";
import Link from "next/link";
import { CalendarClock, Check, Copy, ExternalLink, Mail, Pencil, Search, Send, UserRound, X } from "lucide-react";
import { Callout, Empty, Err, Loading, PageHeader, Tabs } from "@/components/ui";
import { CompanyLogo } from "@/components/visual";
import { api, day, useApi } from "@/lib/api";

const TABS: [string, string, string[]][] = [
  ["todo", "To send", ["ready", "drafted", "scheduled"]],
  ["waiting", "Sent", ["sent", "connected"]],
  ["replied", "Replied", ["replied"]],
  ["done", "Skipped", ["skipped", "bounced"]],
];
const STATUS: Record<string, string> = { ready: "Ready", drafted: "Draft in Gmail", scheduled: "Approved", sent: "Sent", connected: "Connected",
  replied: "Replied", skipped: "Skipped", bounced: "Bounced" };
const TZ = "America/Phoenix";  // Noderze's send times are set in your time zone
const TRACK: Record<string, string> = { data: "Data", cyber: "Cybersecurity", network: "Networking", it: "IT" };

export default function Outreach() {
  const { data, error, reload } = useApi<any>("/api/prospects");
  const [tab, setTab] = useState("todo");
  const [copied, setCopied] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [edit, setEdit] = useState<{ id: number; subject: string; body: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function set(id: number, status: string) { try { await api(`/api/prospects/${id}`, { method: "PATCH", body: { status } }); reload(); } catch {} }
  async function saveEdit() {
    if (!edit) return;
    try { await api(`/api/prospects/${edit.id}`, { method: "PATCH", body: { subject: edit.subject, body: edit.body } }); setEdit(null); reload(); } catch (e: any) { setErr(e.message); }
  }
  async function batch(path: string, ids?: number[]) {
    setBusy(true); setErr(null);
    try { await api(path, { body: { ids: ids || null } }); reload(); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  function copy(id: number, text: string) { navigator.clipboard.writeText(text); setCopied(id); setTimeout(() => setCopied(null), 2500); }
  const items: any[] = data?.items || [];
  const of = (k: string) => items.filter((p) => TABS.find(([t]) => t === k)![2].includes(p.status));
  const shown = of(tab).sort((a, b) => (a.channel === "email" ? 0 : 1) - (b.channel === "email" ? 0 : 1));
  const c = data?.counts || {};
  const sending = data?.sending || {};
  const waiting = items.filter((p) => p.channel === "email" && ["ready", "drafted"].includes(p.status));
  const scheduled = items.filter((p) => p.status === "scheduled");
  const due = (data?.applications || []).filter((a: any) => a.due);
  return (
    <>
      <PageHeader title="Internship outreach"
        lede={<>People to ask about a spring 2027 internship, posting or not, and follow-ups on internships you applied to. Nothing goes out until you approve it: emails send at the time shown after you approve the day's batch, and LinkedIn notes are copied for you to paste.</>}
        actions={data?.last_batch ? <span className="small muted">Last batch {day(data.last_batch)}</span> : undefined} />
      <Err msg={error} />
      {!data ? <Loading what="Loading outreach" /> : <>
        <div className="stats" style={{ display: "flex", gap: "1.6rem", margin: ".2rem 0 1rem", flexWrap: "wrap" }}>
          <div><div className="num" style={{ fontSize: "1.6rem", fontWeight: 800 }}>{c.to_send || 0}</div><div className="tiny muted">to send</div></div>
          <div><div className="num" style={{ fontSize: "1.6rem", fontWeight: 800 }}>{c.reached || 0}</div><div className="tiny muted">reached</div></div>
          <div><div className="num" style={{ fontSize: "1.6rem", fontWeight: 800 }}>{c.replied || 0}</div><div className="tiny muted">replied</div></div>
        </div>
        <section className="panel" style={{ marginBottom: "1.2rem" }}>
          <div className="spread" style={{ alignItems: "center", gap: ".8rem", flexWrap: "wrap" }}>
            <div>
              <h3><CalendarClock size={17} style={{ verticalAlign: "-3px", marginRight: ".35rem" }} />Today's blueprint</h3>
              <p className="small muted" style={{ marginTop: ".25rem", maxWidth: "70ch" }}>
                {waiting.length ? <>{waiting.length} email{waiting.length > 1 ? "s" : ""} waiting for your approval. Read or edit them below, then approve; they go out {fmt(sending.next_send_at)} from {sending.address || "your Gmail"}.</>
                  : scheduled.length ? <>{scheduled.length} approved email{scheduled.length > 1 ? "s" : ""} going out {fmt(scheduled[0].send_at)}. You can still edit or cancel them.</>
                  : <>No emails waiting. A new batch arrives every weekday afternoon.</>}
                {due.length > 0 && <> {due.length} internship{due.length > 1 ? "s" : ""} you applied to {due.length > 1 ? "are" : "is"} due for a follow-up in the next batch.</>}</p>
            </div>
            <div className="row" style={{ gap: ".5rem" }}>
              {waiting.length > 0 && sending.ready && <button className="btn primary" disabled={busy} onClick={() => batch("/api/prospects/approve")}><Send />Approve {waiting.length} for {fmt(sending.next_send_at)}</button>}
              {scheduled.length > 0 && <button className="btn quiet" disabled={busy} onClick={() => batch("/api/prospects/unschedule")}>Cancel the batch</button>}
            </div>
          </div>
          {waiting.length > 0 && !sending.ready && <div style={{ marginTop: ".8rem" }}><Callout tone="warn" action={<Link className="btn sm" href="/settings#gmail">Connect Gmail</Link>}>
            To approve a batch and have it sent at {fmt(sending.next_send_at)}, connect Gmail sending in Settings (one time). Until then, open each draft below and click Send in Gmail.</Callout></div>}
          <Err msg={err} />
        </section>
        <Tabs value={tab} onChange={setTab} tabs={TABS.map(([k, l]) => [k, l, of(k).length])} />
        {tab === "todo" && shown.length > 0 && <p className="small muted" style={{ margin: "-.2rem 0 .8rem", maxWidth: "80ch" }}>
          <b>Emails:</b> approve the batch above, or open a draft and click Send yourself. <b>LinkedIn:</b> the button copies the note and opens that company's campus recruiters; connect with the first one whose headline says university, campus or early careers recruiter there, then Add a note and paste. Out of free notes this month? Connect without one and send the follow-up message once they accept.</p>}
        <div className="list outreach">
          {shown.length ? shown.map((p) => (
            <div key={p.id} className="li" style={{ alignItems: "flex-start" }}>
              <CompanyLogo name={p.company} website={p.company_website} size="sm" />
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="row" style={{ gap: ".45rem", flexWrap: "wrap" }}>
                  <span className="title">{p.company}</span>
                  <span className="tag">{p.channel === "email" ? <><Mail />Email</> : <><UserRound />LinkedIn</>}</span>
                  {p.kind === "applied" && <span className="tag good">You applied{p.job_title ? `: ${p.job_title}` : ""}</span>}
                  {p.track && <span className="tag">{TRACK[p.track] || p.track}</span>}
                  <span className={`tag ${p.status === "replied" ? "good" : p.status === "bounced" ? "bad" : ""}`}>{STATUS[p.status] || p.status}</span>
                </div>
                <div className="sub">{p.name ? `${p.name}${p.title ? `, ${p.title}` : ""}` : p.title || (p.channel === "email" ? "Team inbox" : "A recruiter there")}{p.email ? ` · ${p.email}` : ""}{p.location ? ` · ${p.location}` : ""}</div>
                {p.why && <div className="snippet">{p.why}</div>}

                {p.channel === "email" && p.status !== "replied" && <>
                  {p.subject && <div className="small" style={{ marginTop: ".45rem" }}><b>Subject:</b> {p.subject}</div>}
                  {p.body && <button className="btn quiet sm" style={{ paddingLeft: 0 }} onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? "Hide the email" : "Read the email"}</button>}
                  {open === p.id && edit?.id !== p.id && <div className="msg" style={{ whiteSpace: "pre-wrap", marginTop: ".3rem" }}>{p.body}</div>}
                  {edit?.id === p.id && <div className="form" style={{ marginTop: ".4rem", maxWidth: 680 }}>
                    <label className="field">Subject<input value={edit.subject} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} /></label>
                    <label className="field">Email<textarea style={{ minHeight: 260 }} value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} /></label>
                    <div className="row"><button className="btn sm primary" onClick={saveEdit}>Save changes</button><button className="btn sm quiet" onClick={() => setEdit(null)}>Cancel</button></div>
                  </div>}
                  {p.status === "scheduled" && <div className="small" style={{ marginTop: ".4rem" }}><CalendarClock size={14} style={{ verticalAlign: "-2px" }} /> Sends {fmt(p.send_at)}</div>}
                  {p.send_error && <div className="small" style={{ marginTop: ".3rem", color: "var(--red, #e66)" }}>{p.send_error}</div>}
                  <div className="row" style={{ marginTop: ".5rem", gap: ".5rem", flexWrap: "wrap" }}>
                    {["ready", "drafted", "scheduled"].includes(p.status) && edit?.id !== p.id && <button className="btn sm" onClick={() => { setEdit({ id: p.id, subject: p.subject || "", body: p.body || "" }); setOpen(p.id); }}><Pencil />Edit</button>}
                    {["ready", "drafted"].includes(p.status) && sending.ready && <button className="btn sm" disabled={busy} onClick={() => batch("/api/prospects/approve", [p.id])}><Send />Approve this one</button>}
                    {p.status === "scheduled" && <button className="btn sm quiet" disabled={busy} onClick={() => batch("/api/prospects/unschedule", [p.id])}>Don't send</button>}
                    {["ready", "drafted"].includes(p.status) && p.draft_url && <a className="btn sm quiet" href={p.draft_url} target="_blank" rel="noreferrer"><ExternalLink />Open the Gmail draft</a>}
                    {["ready", "drafted"].includes(p.status) && <button className="btn sm quiet" onClick={() => set(p.id, "sent")}><Check />I sent it myself</button>}
                  </div>
                </>}

                {p.channel === "linkedin" && p.status !== "replied" && <>
                  {p.note && ["ready"].includes(p.status) && <div className="msg" style={{ marginTop: ".45rem" }}>{p.note}<div className="tiny muted" style={{ marginTop: ".3rem" }}>{p.note.length} of 200 characters</div></div>}
                  {p.followup && p.status === "ready" && <button className="btn quiet sm" style={{ paddingLeft: 0 }} onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? "Hide the follow-up message" : "See the follow-up message"}</button>}
                  {p.followup && p.status === "ready" && open === p.id && <div className="msg" style={{ whiteSpace: "pre-wrap" }}>{p.followup}</div>}
                  {p.followup && ["sent", "connected"].includes(p.status) && <div className="msg" style={{ marginTop: ".45rem", whiteSpace: "pre-wrap" }}>{p.followup}<div className="tiny muted" style={{ marginTop: ".3rem" }}>Send this once they accept</div></div>}
                  <div className="row" style={{ marginTop: ".5rem", gap: ".5rem", flexWrap: "wrap" }}>
                    {p.status === "ready" && p.linkedin_url && <button className="btn sm primary" onClick={() => { copy(p.id, p.note || ""); window.open(p.linkedin_url, "_blank", "noopener"); }}>
                      <Copy />{copied === p.id ? "Copied. Paste it in the note" : p.linkedin_url.includes("/search/") ? "Copy the note and find a recruiter" : "Copy the note and open the profile"}</button>}
                    {p.status === "ready" && <button className="btn sm" onClick={() => set(p.id, "sent")}><Check />I sent the request</button>}
                    {p.status === "ready" && p.searches?.length > 1 && <span className="tiny muted" style={{ alignSelf: "center" }}>
                      Nobody right? Try {p.searches.slice(1).map((s: any, i: number) => <span key={s.label}>{i ? " or " : ""}<a href={s.url} target="_blank" rel="noreferrer" onClick={() => copy(p.id, p.note || "")}>{s.label.toLowerCase()}</a></span>)}</span>}
                    {["sent", "connected"].includes(p.status) && p.followup && <button className="btn sm" onClick={() => { copy(p.id, p.followup); if (p.linkedin_url) window.open(p.linkedin_url, "_blank", "noopener"); }}>
                      <Copy />{copied === p.id ? "Copied" : "They accepted: copy the message"}</button>}
                    {p.status === "sent" && <button className="btn sm quiet" onClick={() => set(p.id, "connected")}>Mark as connected</button>}
                  </div>
                </>}
                <div className="tiny faint" style={{ marginTop: ".4rem" }}>
                  {p.sent_at ? `Sent ${day(p.sent_at)}. ` : ""}{p.replied_at ? `Replied ${day(p.replied_at)}. ` : ""}
                  {p.source_url && <a href={p.source_url} target="_blank" rel="noreferrer">Where this contact came from</a>}
                </div>
              </div>
              <div className="end">
                {["ready", "drafted", "sent", "connected"].includes(p.status) && <button className="btn sm quiet" onClick={() => set(p.id, "replied")}>They replied</button>}
                {["ready", "drafted"].includes(p.status) && <button className="btn sm quiet icon" title="Skip this one" aria-label="Skip" onClick={() => set(p.id, "skipped")}><X /></button>}
                {["skipped", "bounced"].includes(p.status) && <button className="btn sm quiet" onClick={() => set(p.id, p.channel === "email" && p.draft_url ? "drafted" : "ready")}>Bring back</button>}
              </div>
            </div>)) : <div className="panel"><Empty title={tab === "todo" ? "Nothing to send right now" : "Nothing here yet"}>
              {tab === "todo" ? "New contacts arrive every weekday morning: emails as Gmail drafts, recruiters as LinkedIn notes." : "Contacts move here as you send them and hear back."}</Empty></div>}
        </div>

        <section className="panel" style={{ marginTop: "1.4rem" }}>
          <h3 style={{ marginBottom: ".3rem" }}><Search size={16} style={{ verticalAlign: "-2px", marginRight: ".35rem" }} />Search LinkedIn postings yourself</h3>
          <p className="small muted" style={{ marginBottom: ".8rem" }}>Google finds LinkedIn postings that LinkedIn's own search can bury; the time filters show only what was posted in the last hour or day, so you can apply early. These open in your browser.</p>
          <div className="stack" style={{ display: "grid", gap: ".45rem" }}>
            {(data.searches || []).map((s: any) => (
              <div key={s.role + s.place} className="row" style={{ gap: ".6rem", flexWrap: "wrap" }}>
                <span className="small" style={{ minWidth: "15rem" }}><b>{s.role}</b>, {s.place}</span>
                <a className="chip" href={s.google} target="_blank" rel="noreferrer">Google</a>
                <a className="chip" href={s.linkedin_hour} target="_blank" rel="noreferrer">Past hour</a>
                <a className="chip" href={s.linkedin_day} target="_blank" rel="noreferrer">Past 24 hours</a>
              </div>))}
          </div>
        </section>
      </>}
    </>
  );
}

/** "Mon, Nov 30, 9:00 AM" in your time zone, from a UTC timestamp. */
function fmt(iso?: string | null) {
  if (!iso) return "at the next send time";
  const d = new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: TZ });
}
