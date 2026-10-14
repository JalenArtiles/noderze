"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Download, ExternalLink, UserSearch } from "lucide-react";
import { Callout, Err, PageHeader, PathBadge } from "@/components/ui";
import { FactChips } from "@/components/intern";
import { CompanyLogo, ScoreRing } from "@/components/visual";
import { api, fileUrl } from "@/lib/api";

const DRAFTS: [string, string][] = [["recruiter_connect", "Recruiter connection note"], ["sdr_manager", "SDR manager note"], ["alumni", "ASU alumni note"], ["recruiter_followup", "Follow-up after they accept"]];
const CAT: Record<string, string> = { fix: "Fix", reorder: "Reorder", keywords: "Keywords", summary: "Summary", rewrite: "Rewrite" };
const GROUPS: [string, string][] = [["on_resume", "Already on your resume"], ["added", "Added from your experience"], ["missing", "Missing. Click \"I have this\" only if it's true"]];

export default function Apply() {
  const { id } = useParams() as { id: string };
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [person, setPerson] = useState<string>("");
  const [kind, setKind] = useState("recruiter_connect");
  const [copied, setCopied] = useState(false);
  const [allChanges, setAllChanges] = useState(false);
  const load = useCallback(async (fresh = false) => {
    setBusy(true);
    try { setD(await api(`/api/apply/${id}${fresh ? "?fresh=true" : ""}`, { body: {} })); setErr(null); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }, [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (d && window.location.hash === "#recruiter") document.getElementById("recruiter")?.scrollIntoView({ behavior: "smooth" }); }, [d]);
  async function claim(term: string) { await api("/api/profile/claims", { body: { term, have: true } }); load(true); }
  async function toggle(e: any) {
    const approve = e.status !== "approved";
    if (approve && e.flags?.length && !confirm(`This change was flagged:\n\n${e.flags.join("\n")}\n\nUse it only if every point is true. Use it?`)) return;
    await api(`/api/resume/versions/${d.version_id}/edits/${e.id}`, { body: { decision: approve ? "approve" : "reject", acknowledge_flags: true } });
    load();
  }
  async function applied() { await api(`/api/applications/${d.application_id}`, { method: "PATCH", body: { stage: "applied" } }); load(); }
  if (err) return <><Err msg={err} />{err.includes("resume") && <p style={{ marginTop: "1rem" }}><Link className="btn primary" href="/resume">Upload your resume</Link></p>}</>;
  if (!d) return <div className="panel empty"><h3>Tailoring your resume</h3><p>Matching your experience to the keywords this company screens for.</p></div>;
  const j = d.job;
  const first = person ? person.split(" ")[0] : "there";
  const msg = (d.drafts[kind] || "").replaceAll("{first}", first);
  const drafts: [string, string][] = d.draft_labels || DRAFTS;
  const it = d.is_intern ? j.intern : null;
  const open = it ? (it.checks || []).filter((c: any) => c.state !== "pass") : [];
  const terms = d.ats.terms;
  const edits = allChanges ? d.edits : d.edits.slice(0, 5);
  return (
    <>
      <PageHeader
        crumb={<Link href={`/companies/${j.company_id}`}>{j.company}</Link>}
        title={<span className="ph-id"><CompanyLogo name={j.company} website={j.company_website} size="lg" /><span>{j.title}</span></span>}
        actions={<><ScoreRing value={j.score_total} /><Link className="btn" href={`/jobs/${j.id}`}>Why it fits</Link></>}>
        <div className="meta">
          {it ? <><span className={`tag track ${it.track}`}>{it.track_label}</span><FactChips it={it} /></> : <><PathBadge value={j.path_class} /><span className="tag">{j.location_text}</span></>}
          {d.se_team?.open_se_roles > 0 && <span className="tag info">{d.se_team.open_se_roles} open SE roles</span>}
          {j.needs_verification && <span className="tag warn">Check the posting is still open</span>}
          {d.stage === "applied" && <span className="tag good"><Check />Applied</span>}
        </div>
      </PageHeader>

      {open.length > 0 && <div style={{ margin: ".4rem 0 1rem" }}><Callout tone={it.status === "out" ? "bad" : "warn"}>
        {it.status === "out" ? "This internship missed one of your rules: " : "Ask the recruiter before you apply: "}
        {open.map((c: any) => c.detail.replace(/\.$/, "")).join("; ")}.</Callout></div>}
      <div className="steps-v">
        <section className="panel">
          <span className="badge-n">1</span>
          <div className="spread" style={{ alignItems: "center" }}>
            <div><h2>Your resume, tailored to {j.company}</h2>
              <p className="small muted" style={{ marginTop: ".3rem", maxWidth: "56ch" }}>Applicant tracking systems rank resumes by keyword match. Noderze only adds terms your experience supports.</p></div>
            <div className="row" style={{ gap: ".6rem" }}>
              <div style={{ textAlign: "center" }}><ScoreRing value={d.ats.before} /><div className="tiny muted">Before</div></div>
              <div style={{ textAlign: "center" }}><ScoreRing value={d.ats.after} /><div className="tiny muted">After</div></div>
            </div>
          </div>
          <div style={{ marginTop: "1rem" }}>
            {GROUPS.map(([k, title]) => {
              const items = terms.filter((t: any) => t.status === k);
              return items.length ? (
                <div key={k} className="kwgroup"><h4>{title} ({items.length})</h4>
                  <div className="chips">{items.map((t: any) => (
                    <span key={t.term} className={`kw ${t.status}`} title={t.typical ? "Typical for this kind of role (the posting text was short)" : `${t.mentions} mention(s) in this posting`}>
                      {t.status === "on_resume" && <Check />}{t.term}
                      {t.status === "missing" && <button onClick={() => claim(t.term)} title="Only if it's true for you">I have this</button>}</span>))}</div></div>) : null;
            })}
          </div>
          <hr />
          <h3 style={{ marginBottom: ".2rem" }}>Changes to your resume</h3>
          {edits.map((e: any) => (
            <div key={e.id} className="change">
              <span className="tag">{CAT[e.category] || e.category}</span>
              <div className="grow">{e.kind === "replace_text" ? <>{e.find} becomes <b>{e.replace}</b></> : e.kind === "reorder" ? "Most relevant line moved first" : (e.text || e.after)}
                {e.flags?.length > 0 && <div className="flag">{e.flags.join(" ")}</div>}</div>
              <button className={`btn sm ${e.status === "approved" ? "" : "dark"}`} onClick={() => toggle(e)}>{e.status === "approved" ? "Undo" : "Use"}</button>
            </div>))}
          {d.edits.length > 5 && <button className="btn quiet sm" onClick={() => setAllChanges(!allChanges)}>{allChanges ? "Show fewer" : `Show all ${d.edits.length} changes`}</button>}
          <div className="row" style={{ marginTop: "1rem" }}>
            <a className="btn primary" href={fileUrl(`/api/resume/versions/${d.version_id}/download`)}><Download />Download tailored resume</a>
            {busy && <span className="small muted">Updating...</span>}</div>
        </section>

        <section className="panel">
          <span className="badge-n">2</span>
          <h2>Apply on {j.company}'s site</h2>
          <p className="small muted" style={{ margin: ".3rem 0 .9rem" }}>Upload the tailored resume you just downloaded, then mark it applied so Noderze can remind you to follow up.{it ? " Before you accept an offer, check with your internship coordinator that it counts for credit." : ""}</p>
          <div className="row">
            {d.apply_url && <a className="btn gold" href={d.apply_url} target="_blank" rel="noreferrer"><ExternalLink />Open the application</a>}
            <button className="btn" onClick={applied} disabled={d.stage === "applied"}><Check />{d.stage === "applied" ? "Marked as applied" : "I applied"}</button>
            <Link className="btn quiet" href={`/applications/${d.application_id}`}>Cover letter and answers</Link>
          </div>
        </section>

        <section className="panel" id="recruiter">
          <span className="badge-n">3</span>
          <h2>Reach a recruiter or hiring manager</h2>
          <p className="small muted" style={{ margin: ".3rem 0 .9rem" }}>These open LinkedIn in your browser. Pick someone, copy the message and send it yourself. Noderze never messages anyone for you.</p>
          <div className="chips" style={{ marginBottom: ".7rem" }}>{d.links.map((l: any) => <a key={l.label} className="chip" href={l.url} target="_blank" rel="noreferrer" title={l.why}><UserSearch />{l.label}</a>)}</div>
          {d.people.length > 0 && <div className="chips" style={{ marginBottom: ".7rem" }}>
            {d.people.slice(0, 8).map((p: any) => (
              <button key={p.id} className={`chip ${person === p.name ? "on" : ""}`} onClick={() => setPerson(p.name)} title={p.reason}>
                {p.connection ? "Connection: " : ""}{p.name}{p.title ? `, ${p.title}` : ""}</button>))}</div>}
          <div className="form" style={{ maxWidth: 560, margin: ".4rem 0 .7rem" }}>
            <label className="field">Their first name<input value={person} onChange={(e) => setPerson(e.target.value)} placeholder="e.g. Taylor" /></label>
            <label className="field">Message<select value={kind} onChange={(e) => setKind(e.target.value)}>{drafts.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          </div>
          <div className="msg">{msg}</div>
          <div className="row" style={{ marginTop: ".6rem" }}>
            <button className="btn dark" onClick={() => { navigator.clipboard.writeText(msg); setCopied(true); setTimeout(() => setCopied(false), 2000); }}><Copy />{copied ? "Copied" : "Copy message"}</button>
            <span className="small muted">{msg.length} characters{["recruiter_connect", "alumni", "sdr_manager"].includes(kind) ? ". Free LinkedIn accounts allow 200 in a connection note." : ""}</span></div>
        </section>
      </div>
    </>
  );
}
