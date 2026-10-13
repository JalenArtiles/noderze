"use client";
import { useEffect, useState } from "react";
import { CheckCircle2, CircleDashed } from "lucide-react";
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
            <div className="li" style={{ alignItems: "flex-start" }}>
              {m?.llm ? <CheckCircle2 style={{ color: "var(--green)" }} /> : <CircleDashed style={{ color: "var(--faint)" }} />}
              <div className="grow"><div className="title">Anthropic API key {m?.llm ? "connected" : "not set"}</div>
                <div className="sub">Writes better cover letters, answers and resume wording, and powers web research by default. Get a key at console.anthropic.com and add <code>ANTHROPIC_API_KEY=</code> to <code>backend/.env</code>.</div></div>
            </div>
            <div className="li" style={{ alignItems: "flex-start" }}>
              {m && m.search_provider !== "none" ? <CheckCircle2 style={{ color: "var(--green)" }} /> : <CircleDashed style={{ color: "var(--faint)" }} />}
              <div className="grow"><div className="title">Web search {m && m.search_provider !== "none" ? `connected (${m.search_provider})` : "not set"}</div>
                <div className="sub">Turns on company research, recruiter and alumni search, and program discovery. An Anthropic key with web search enabled covers it, or add a Tavily, Brave or Serper key to <code>backend/.env</code>.</div></div>
            </div>
          </div>
          <p className="small faint" style={{ marginTop: ".5rem" }}>Noderze picks up changes to backend/.env the next time it starts.</p>
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
