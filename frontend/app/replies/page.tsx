"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ExternalLink, Inbox, MailCheck, X } from "lucide-react";
import { Callout, Empty, Err, Loading, PageHeader, SectionHead, stageLabel } from "@/components/ui";
import { CompanyLogo } from "@/components/visual";
import { api, day, useApi } from "@/lib/api";

const FILTERS: [string, string][] = [["needs", "Needs you"], ["all", "All"], ["interview", "Interviews"], ["assessment", "Assessments"],
  ["rejection", "Not moving forward"], ["confirmation", "Application received"]];
const TONE: Record<string, string> = { interview: "good", assessment: "good", offer: "good", rejection: "bad", confirmation: "", other: "info" };

function ago(iso?: string | null) {
  if (!iso) return null;
  const m = Math.round((Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 60000);
  return m < 2 ? "just now" : m < 60 ? `${m} minutes ago` : m < 48 * 60 ? `${Math.round(m / 60)} hours ago` : `${Math.round(m / 1440)} days ago`;
}

export default function Replies() {
  const { data, error, reload } = useApi<any>("/api/replies");
  const [filter, setFilter] = useState("needs");
  const [fresh, setFresh] = useState<Set<number>>(new Set());
  const marked = useRef(false);
  // Opening the page counts as reading: the badge clears, but this visit still highlights what was new.
  useEffect(() => {
    if (!data || marked.current) return;
    marked.current = true;
    const unread = data.items.filter((r: any) => !r.seen).map((r: any) => r.id);
    if (!unread.length) return;
    setFresh(new Set(unread));
    api("/api/replies/seen", { body: {} }).then(() => window.dispatchEvent(new CustomEvent("noderze:counts", { detail: { replies: 0 } }))).catch(() => {});
  }, [data]);
  async function act(path: string, body?: any, method = "POST") { try { await api(path, { method, body: body || {} }); reload(); } catch {} }
  const items: any[] = data?.items || [];
  const shown = items.filter((r) => filter === "all" || (filter === "needs" ? r.needs_you : r.kind === filter));
  const count = (f: string) => items.filter((r) => f === "all" || (f === "needs" ? r.needs_you : r.kind === f)).length;
  return (
    <>
      <PageHeader title="Replies"
        lede={<>Emails from companies you applied to: interview requests, assessments, rejections and confirmations. Everything else in your inbox is ignored.</>}
        actions={data?.last_check ? <span className="small muted">Last checked {ago(data.last_check)}</span> : undefined} />
      <Err msg={error} />
      {!data ? <Loading what="Loading replies" /> : <>
        <div className="toolbar">
          <div className="chips">{FILTERS.map(([k, l]) => (
            <button key={k} className={`chip ${filter === k ? "on" : ""}`} onClick={() => setFilter(k)}>{l}<span className="n num">{count(k)}</span></button>))}</div>
        </div>
        <div className="list replies">
          {shown.length ? shown.map((r) => (
            <div key={r.id} className={`li ${fresh.has(r.id) ? "unread" : ""}`}>
              <CompanyLogo name={r.company || r.from_name || "?"} size="sm" />
              <div className="grow">
                <div className="row" style={{ gap: ".45rem" }}>
                  <span className="title">{r.subject || "(no subject)"}</span>
                  <span className={`tag ${TONE[r.kind] || ""}`}>{r.kind_label}</span>
                </div>
                <div className="sub">
                  {r.company}{r.job_title ? `, ${r.job_title}` : ""}{r.stage ? ` (${stageLabel(r.stage)})` : ""} · {r.from_name && r.from_name !== r.company ? r.from_name : r.from_email}{r.received_at ? ` · ${day(r.received_at)}` : ""}
                </div>
                {r.snippet && <div className="snippet">{r.snippet}</div>}
                <div className="row" style={{ marginTop: ".55rem" }}>
                  {r.url && <a className="btn sm" href={r.url} target="_blank" rel="noreferrer"><ExternalLink />Open in Gmail</a>}
                  {r.suggest && <button className="btn sm primary" onClick={() => act(`/api/replies/${r.id}/apply`)}><MailCheck />{r.suggest.label}</button>}
                  {r.application_id && <Link className="btn sm quiet" href={`/applications/${r.application_id}`}>Open the application</Link>}
                  <button className="btn sm quiet icon" title="Dismiss" aria-label="Dismiss" onClick={() => act(`/api/replies/${r.id}`, { dismissed: true }, "PATCH")}><X /></button>
                </div>
              </div>
            </div>)) :
            <Empty title={items.length ? "Nothing here" : "No replies yet"}>
              {items.length ? "Try another filter." : "When a company you applied to emails you, it shows up here and in the bar at the top."}</Empty>}
        </div>

        <div className="sec">
          <SectionHead title="How replies get here" />
          <section className="panel stack">
            <p className="small">A scheduled Claude task reads your Gmail through your Claude account's Gmail connection a few times a day, while your computer is on. It looks only for emails from the {data.watching} {data.watching === 1 ? "company" : "companies"} you have an application with, and from the job sites they use (Greenhouse, Workday, Lever, Handshake and others). Noderze keeps only the emails that match one of your applications and never sends anything.</p>
            {data.accounts?.length > 0 && <p className="small muted">Emails so far came in to: {data.accounts.join(", ")}.</p>}
            <Callout>To include your other inboxes, have them forward to the one connected to Claude. In Gmail, open Settings, then Forwarding and POP/IMAP, and add the connected address. Your ASU email already arrives there.</Callout>
            {!data.last_check && <p className="small muted"><Inbox size={14} style={{ verticalAlign: "-2px" }} /> The first check hasn't run yet.</p>}
          </section>
        </div>
      </>}
    </>
  );
}
