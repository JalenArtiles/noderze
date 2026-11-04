"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, CircleDashed, Undo2 } from "lucide-react";
import { Callout, Err, Loading, PageHeader, SectionHead } from "@/components/ui";
import { api, day, useApi } from "@/lib/api";
import ThemePicker from "@/components/theme-picker";

const LABELS: Record<string, string> = { career_path: "Career path", technical_fit: "Technical fit", geography: "Geography", development: "Development program",
  eligibility: "Eligibility and timing", sales_leverage: "Sales experience", compensation: "Compensation", evidence: "Evidence strength" };
const STATES = ["AZ", "CA", "NV", "TX", "CO", "UT", "WA", "OR", "NM", "FL", "NY", "NC", "GA", "IL", "MA"];

export default function Settings() {
  const { data, error, reload } = useApi("/api/profile");
  const meta = useApi("/api/meta");
  const rules = useApi<any[]>("/api/alert-rules");
  const removed = useApi<any[]>("/api/removed");
  const replies = useApi<any>("/api/replies");
  const [w, setW] = useState<Record<string, number>>({});
  const [p, setP] = useState<any>(null);
  const [json, setJson] = useState("");
  const [msg, setMsg] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (data) { setW(data.weights); setP(data.data || {}); setJson(JSON.stringify(data.data, null, 2)); } }, [data]);
  useEffect(() => { if (window.location.hash) setTimeout(() => document.querySelector(window.location.hash)?.scrollIntoView(), 300); }, [meta.data]);
  const total = Object.values(w).reduce((a, b) => a + Number(b), 0);
  async function save(body: any) {
    setMsg("Saving and rescoring every role. This takes a few seconds.");
    try { const r = await api("/api/profile", { method: "PUT", body }); setMsg(`Saved. Rescored ${r.rescored} roles.`); setErr(null); reload(); } catch (e: any) { setErr(e.message); setMsg(null); }
  }
  const loc = p?.locations || {};
  const setLoc = (k: string, v: any) => setP({ ...p, locations: { ...loc, [k]: v } });
  async function toggle(r: any) { await api(`/api/alert-rules/${r.id}`, { method: "PATCH", body: { enabled: !r.enabled } }); rules.reload(); }
  const m = meta.data;
  return (
    <>
      <PageHeader title="Settings" lede="Your profile, how roles are scored, and what Noderze connects to." />
      <Err msg={error || err} />
      {msg && <div style={{ marginBottom: "1rem" }}><Callout>{msg}</Callout></div>}
      <div id="appearance" style={{ marginBottom: "2.2rem" }}>
        <SectionHead title="Appearance" aside={<span className="muted">Changes apply right away</span>} />
        <ThemePicker />
      </div>
      {!p ? <Loading /> : <>
        <SectionHead title="About you" />
        <section className="panel stack">
          <div className="form">
            <label className="field">Name<input value={p.name || ""} onChange={(e) => setP({ ...p, name: e.target.value })} /></label>
            <label className="field">Graduation month<input type="month" value={p.expected_graduation || ""} onChange={(e) => setP({ ...p, expected_graduation: e.target.value })} /></label>
            <label className="field">Can start full-time<input type="month" value={p.available_start || ""} onChange={(e) => setP({ ...p, available_start: e.target.value })} /></label>
            <label className="field">Base pay you're aiming for<input type="number" step={1000} value={p.comp_target || ""} onChange={(e) => setP({ ...p, comp_target: +e.target.value })} /></label>
          </div>
          <div className="form">
            <label className="field">Home state<select value={(loc.primary_states || ["AZ"])[0]} onChange={(e) => setLoc("primary_states", [e.target.value])}>{STATES.map((s) => <option key={s}>{s}</option>)}</select></label>
            <label className="field">Work authorization<input placeholder="e.g. US citizen, no sponsorship needed" value={p.work_authorization || ""} onChange={(e) => setP({ ...p, work_authorization: e.target.value })} /></label>
          </div>
          <div className="row">
            <label className="check"><input type="checkbox" checked={loc.remote_ok !== false} onChange={(e) => setLoc("remote_ok", e.target.checked)} />Remote roles count as near me</label>
            <label className="check"><input type="checkbox" checked={(loc.acceptable_regions || []).includes("socal")} onChange={(e) => setLoc("acceptable_regions", e.target.checked ? ["socal"] : [])} />Southern California works too</label>
          </div>
          <label className="field">Your story, in a sentence or two<textarea style={{ minHeight: 80 }} placeholder="Why you want sales engineering. Interview answers and cover letters open with it." value={p.story_hook || ""} onChange={(e) => setP({ ...p, story_hook: e.target.value })} /></label>
          <div><button className="btn primary" onClick={() => save({ data: p })}>Save and rescore</button></div>
        </section>

        <div className="sec" id="connections">
          <SectionHead title="Connections" />
          <div className="list">
            <AnthropicKey connected={!!m?.llm} onChange={meta.reload} />
            <div className="li" style={{ alignItems: "flex-start" }}>
              {replies.data?.last_check ? <CheckCircle2 style={{ color: "var(--green)" }} /> : <CircleDashed style={{ color: "var(--faint)" }} />}
              <div className="grow"><div className="title">Email replies {replies.data?.last_check ? `checked ${day(replies.data.last_check)}` : "waiting for the first check"}</div>
                <div className="sub">A scheduled Claude task reads your Gmail a few times a day and drops replies from companies you applied to into <Link href="/replies">Replies</Link>. Nothing is ever sent.</div></div>
            </div>
            <div className="li" style={{ alignItems: "flex-start" }}>
              {m && m.search_provider !== "none" ? <CheckCircle2 style={{ color: "var(--green)" }} /> : <CircleDashed style={{ color: "var(--faint)" }} />}
              <div className="grow"><div className="title">Web search {m && m.search_provider !== "none" ? `connected (${m.search_provider})` : "not set"}</div>
                <div className="sub">Turns on company research, recruiter and alumni search, and program discovery. An Anthropic key with web search enabled covers it, or add a Tavily, Brave or Serper key to <code>backend/.env</code>.</div></div>
            </div>
          </div>
          <p className="small faint" style={{ marginTop: ".5rem" }}>Other keys in backend/.env are picked up the next time Noderze starts.</p>
        </div>

        <div className="sec" id="removed">
          <SectionHead title="Removed listings" count={removed.data?.length ?? null} aside={<span className="muted">Roles and internships you removed</span>} />
          {!removed.data ? <Loading /> : !removed.data.length ? <p className="small muted">Nothing removed. The X on any listing removes it from every list.</p> :
            <div className="list">{removed.data.map((j: any) => (
              <div key={j.id} className="li compact">
                <div className="grow"><Link href={`/jobs/${j.id}`} className="title">{j.title}</Link><div className="sub">{j.company}, {j.kind === "internship" ? "spring internship" : "career role"}</div></div>
                <button className="btn sm" onClick={async () => { await api(`/api/jobs/${j.id}`, { method: "PATCH", body: { hidden: false } }); removed.reload(); }}><Undo2 />Bring back</button>
              </div>))}</div>}
        </div>

        <div className="sec">
          <SectionHead title="How roles are scored" aside={<span className="muted">Only the relative size matters. Total {total}.</span>} />
          <section className="panel">
            <div className="bars" style={{ gridTemplateColumns: "minmax(150px, 200px) 1fr 44px" }}>
              {Object.keys(LABELS).map((k) => (<div key={k} style={{ display: "contents" }}><label htmlFor={k} className="small">{LABELS[k]}</label>
                <input id={k} type="range" min={0} max={40} value={w[k] ?? 0} onChange={(e) => setW({ ...w, [k]: +e.target.value })} style={{ accentColor: "var(--maroon)", padding: 0, border: 0 }} /><span className="num small">{w[k]}</span></div>))}
            </div>
            <button className="btn dark" style={{ marginTop: ".9rem" }} onClick={() => save({ weights: w })}>Save weights and rescore</button>
          </section>
        </div>

        <div className="sec">
          <SectionHead title="Scheduled scans" aside={<span className="muted">Times are Arizona time, while Noderze is running</span>} />
          <div className="list">{rules.data?.map((r) => (
            <div key={r.id} className="li compact"><div className="grow"><div className="title" style={{ fontWeight: 600 }}>{r.name}</div><div className="sub">{r.last_run_at ? `Last ran ${day(r.last_run_at)}` : "Hasn't run yet"}</div></div>
              <span className={`tag ${r.enabled ? "good" : ""}`}>{r.enabled ? "On" : "Paused"}</span>
              <button className="btn sm" onClick={() => toggle(r)}>{r.enabled ? "Pause" : "Turn on"}</button></div>))}</div>
        </div>

        <div className="sec">
          <details className="panel more-info"><summary>Advanced: edit the full profile</summary>
            <p className="small muted" style={{ marginBottom: ".6rem" }}>Everything Noderze knows about you, as JSON: skills, coursework, certifications, focus and more.</p>
            <textarea value={json} onChange={(e) => setJson(e.target.value)} style={{ minHeight: 360, fontSize: ".85rem", fontFamily: "ui-monospace, Consolas, monospace" }} />
            <button className="btn dark" style={{ marginTop: ".6rem" }} onClick={() => { try { save({ data: JSON.parse(json) }); } catch { setErr("That isn't valid JSON. Check for a missing comma or quote."); } }}>Save profile</button>
          </details>
        </div>
      </>}
    </>
  );
}

/** Paste your Anthropic key once: Noderze checks it, saves it to backend/.env on this computer and uses it right away. */
function AnthropicKey({ connected, onChange }: { connected: boolean; onChange: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function save(value: string) {
    setBusy(true); setErr(null); setMsg(null);
    try { const r = await api("/api/settings/anthropic-key", { body: { key: value } }); setKey(""); setMsg(r.llm ? "Connected. Answers and cover letters are now written by Claude." : "Key removed."); onChange(); }
    catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  return (
    <div className="li" style={{ alignItems: "flex-start" }}>
      {connected ? <CheckCircle2 style={{ color: "var(--green)" }} /> : <CircleDashed style={{ color: "var(--faint)" }} />}
      <div className="grow stack" style={{ gap: ".5rem" }}>
        <div><div className="title">Anthropic API key {connected ? "connected" : "not set"}</div>
          <div className="sub">Writes your application answers and cover letters for the exact question, and powers web research. Create a key at console.anthropic.com under API keys (it starts with sk-ant-), then paste it here. It stays on this computer.</div></div>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={connected ? "Paste a new key to replace it" : "sk-ant-..."} style={{ flex: 1, maxWidth: 420 }} aria-label="Anthropic API key" />
          <button className="btn sm primary" onClick={() => save(key.trim())} disabled={busy || !key.trim()}>{busy ? "Checking" : "Save key"}</button>
          {connected && <button className="btn sm quiet" onClick={() => save("")} disabled={busy}>Remove</button>}
        </div>
        <Err msg={err} />{msg && <span className="small muted">{msg}</span>}
      </div>
    </div>
  );
}
