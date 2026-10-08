"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Download, ExternalLink, UserSearch } from "lucide-react";
import { Err, PathBadge } from "@/components/ui";
import { CompanyLogo, ScoreRing } from "@/components/visual";
import { api, fileUrl } from "@/lib/api";

const DRAFTS: [string, string][] = [["recruiter_connect", "Recruiter connection note"], ["sdr_manager", "SDR manager note"], ["alumni", "ASU alumni note"], ["recruiter_followup", "Follow-up after they accept"]];
const CAT: Record<string, string> = { fix: "Fix", reorder: "Reorder", keywords: "Keywords", summary: "Summary", rewrite: "Rewrite" };

export default function Apply() {
  const { id } = useParams() as { id: string };
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [person, setPerson] = useState<string>("");
  const [kind, setKind] = useState("recruiter_connect");
  const [copied, setCopied] = useState(false);
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
  if (err) return <><Err msg={err} />{err.includes("resume") && <p><Link className="btn" href="/resume">Upload your resume</Link></p>}</>;
  if (!d) return <div className="panel empty">Tailoring your resume to this company's keywords...</div>;
  const j = d.job;
  const first = person ? person.split(" ")[0] : "there";
  const msg = (d.drafts[kind] || "").replaceAll("{first}", first);
  const terms = d.ats.terms;
  return (
    <>
      <div className="spread">
        <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
          <CompanyLogo name={j.company} website={j.company_website} size="lg" />
          <div><div className="small"><Link href={`/companies/${j.company_id}`}>{j.company}</Link></div><h1>{j.title}</h1>
            <div className="row small"><PathBadge value={j.path_class} /><span className="muted">{j.location_text}</span>
              {d.se_team?.open_se_roles > 0 && <span className="badge good">SE team: {d.se_team.open_se_roles} open SE roles</span>}
              {j.needs_verification && <span className="badge warn">Confirm the posting is still open</span>}
              {d.stage === "applied" && <span className="badge good"><Check size={12} />Applied</span>}</div></div>
        </div>
        <ScoreRing value={j.score_total} size="lg" />
      </div>

      <section className="panel stack" style={{ marginTop: "1.2rem" }}>
        <div className="step"><span className="num-badge">1</span><div>
          <h2 style={{ marginTop: 0 }}>Your resume, tailored to {j.company}'s keywords</h2>
          <div className="row" style={{ gap: "1.2rem" }}>
            <div style={{ textAlign: "center" }}><ScoreRing value={d.ats.before} /><div className="small muted">Before</div></div>
            <span className="muted" style={{ fontSize: "1.4rem" }}>to</span>
            <div style={{ textAlign: "center" }}><ScoreRing value={d.ats.after} /><div className="small muted">After</div></div>
            <p className="small muted" style={{ maxWidth: "48ch" }}>Keyword match is how applicant tracking systems rank resumes. Noderze only adds terms your experience supports; anything else stays missing until you confirm it.</p>
          </div>
          <div className="chips" style={{ margin: ".8rem 0" }}>
            {terms.map((t: any) => (
              <span key={t.term} className={`kw ${t.status}`} title={t.typical ? "Typical for this role type (posting text was short)" : `${t.mentions} mention(s) in this posting`}>
                {t.status === "on_resume" ? <Check size={13} /> : null}{t.term}
                {t.status === "missing" && <button onClick={() => claim(t.term)} title="Only if it's true for you">I have this</button>}</span>))}
          </div>
          <div className="small muted">Green: already on your resume. Blue: added from your experience. Gray: missing; click "I have this" only if it's true.</div>
          <h3 style={{ marginTop: "1rem" }}>Changes made</h3>
          {d.edits.map((e: any) => (
            <div key={e.id} className="fact row small" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
              <span className="badge">{CAT[e.category] || e.category}</span>
              <span style={{ flex: 1 }}>{e.kind === "replace_text" ? <>{e.find} becomes <b>{e.replace}</b></> : e.kind === "reorder" ? "Most relevant bullet moved first" : (e.text || e.after)}
                {e.flags?.length > 0 && <span style={{ color: "var(--red)", display: "block" }}>{e.flags.join(" ")}</span>}</span>
              <button className="btn secondary small" onClick={() => toggle(e)}>{e.status === "approved" ? "Undo" : "Use"}</button>
            </div>))}
          <div className="row" style={{ marginTop: ".8rem" }}>
            <a className="btn primary" href={fileUrl(`/api/resume/versions/${d.version_id}/download`)}><Download />Download tailored resume (.docx)</a>
            {busy && <span className="small muted">Updating...</span>}</div>
        </div></div>
      </section>

      <section className="panel" style={{ marginTop: ".9rem" }}>
        <div className="step"><span className="num-badge">2</span><div>
          <h2 style={{ marginTop: 0 }}>Apply</h2>
          <p className="small muted">Opens the company's own application page. Upload the tailored resume you just downloaded.</p>
          <div className="row">
            {d.apply_url && <a className="btn gold" href={d.apply_url} target="_blank" rel="noreferrer"><ExternalLink />Open the application page</a>}
            <button className="btn secondary" onClick={applied} disabled={d.stage === "applied"}><Check />{d.stage === "applied" ? "Marked as applied" : "I applied"}</button>
            <Link className="btn secondary" href={`/applications/${d.application_id}`}>Cover letter and answers</Link>
          </div>
        </div></div>
      </section>

      <section className="panel" id="recruiter" style={{ marginTop: ".9rem" }}>
        <div className="step"><span className="num-badge">3</span><div>
          <h2 style={{ marginTop: 0 }}>Reach a recruiter or hiring manager</h2>
          <p className="small muted">These open LinkedIn in your own browser, where you're logged in. Pick someone, paste the message, and send it yourself. Noderze never messages anyone for you.</p>
          {d.people.length > 0 && <div className="chips" style={{ marginBottom: ".7rem" }}>
            {d.people.slice(0, 8).map((p: any) => (
              <button key={p.id} className={`chip ${person === p.name ? "on" : ""}`} onClick={() => setPerson(p.name)} title={p.reason}>
                {p.connection ? "Connection: " : ""}{p.name}{p.title ? `, ${p.title}` : ""}</button>))}</div>}
          <div className="chips">{d.links.map((l: any) => <a key={l.label} className="chip" href={l.url} target="_blank" rel="noreferrer" title={l.why}><UserSearch />{l.label}</a>)}</div>
          <div className="row" style={{ margin: ".9rem 0 .4rem" }}>
            <label className="small">Their first name <input value={person} onChange={(e) => setPerson(e.target.value)} placeholder="e.g. Taylor" style={{ width: 160 }} /></label>
            <select value={kind} onChange={(e) => setKind(e.target.value)}>{DRAFTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
          <div className="msg">{msg}</div>
          <div className="row" style={{ marginTop: ".5rem" }}>
            <button className="btn" onClick={() => { navigator.clipboard.writeText(msg); setCopied(true); setTimeout(() => setCopied(false), 2000); }}><Copy />{copied ? "Copied" : "Copy message"}</button>
            <span className="small muted">{msg.length} characters{kind !== "recruiter_followup" ? " (LinkedIn connection notes allow up to 200 on free accounts)" : ""}</span></div>
        </div></div>
      </section>
    </>
  );
}
