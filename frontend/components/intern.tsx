"use client";
import Link from "next/link";
import { useState } from "react";
import { CalendarRange, Check, CircleDollarSign, Clock, EyeOff, MapPin, Minus, TriangleAlert, UserSearch, X } from "lucide-react";
import { ScoreChip } from "@/components/ui";
import { CompanyLogo } from "@/components/visual";
import { api, day, label } from "@/lib/api";

export const TRACKS: [string, string][] = [["cyber", "Cybersecurity"], ["data", "Data analytics"], ["network", "Networking"]];
const STATE_ICON: Record<string, any> = { pass: Check, warn: TriangleAlert, fail: X };
const CHECK_ICON: Record<string, any> = { pay: CircleDollarSign, hours: Clock, term: CalendarRange, where: MapPin };

/** Short versions of the four facts that decide an internship, for cards. */
export const CHECK_NAME: Record<string, string> = { field: "the field", pay: "pay", hours: "weekly hours", term: "dates", where: "location", level: "level", open: "that it's open" };
const TONE: Record<string, string> = { pass: "", warn: "warn", fail: "bad" };

export function shortFacts(it: any) {
  const pay = it.pay || {}, hours = it.hours || {}, term = it.term || {}, where = it.where || {};
  const st = (k: string) => (it.checks || []).find((c: any) => c.key === k)?.state || "pass";
  const payText = st("pay") === "pass" && it.overrides?.paid && pay.status !== "amount" ? "Paid (you confirmed)"
    : pay.status === "amount" ? pay.label.replace(" an hour", "/hr").replace(" a year (annualized)", "/yr")
    : pay.status === "stated" ? "Paid, rate not listed" : pay.status === "unpaid" ? "Unpaid"
    : st("pay") === "warn" ? "Pay not read yet" : "No pay listed";
  const hoursText = hours.status === "ok" ? hours.label.replace(" hours a week", " hrs/wk").replace(/^up to/, "Up to").replace(/^at least/, "At least")
    : hours.status === "part_time" ? "Part-time" : hours.status === "unknown" ? "Hours not listed" : hours.label?.split(";")[0].split(",")[0].replace(" hours a week", " hrs/wk");
  const termText = term.status === "unknown" ? "Dates not listed" : term.label;
  return [
    { key: "pay", icon: CircleDollarSign, text: payText, tone: st("pay") === "pass" && pay.status === "amount" ? "good" : TONE[st("pay")] },
    { key: "hours", icon: Clock, text: hoursText, tone: TONE[st("hours")] },
    { key: "term", icon: CalendarRange, text: termText, tone: TONE[st("term")] },
    { key: "where", icon: MapPin, text: where.label, tone: TONE[st("where")] },
  ];
}

export function FactChips({ it }: { it: any }) {
  return <>{shortFacts(it).map((f) => { const Icon = f.icon; return <span key={f.key} className={`tag ifact ${f.tone}`}><Icon />{f.text}</span>; })}</>;
}

/** Your own confirmations: they never get overwritten by a scan. */
export function useInternActions(job: any, onChange?: (it: any) => void) {
  const [busy, setBusy] = useState(false);
  async function set(body: any) {
    setBusy(true);
    try { const r = await api(`/api/internships/${job.id}`, { method: "PATCH", body }); onChange?.(r); } catch {}
    setBusy(false);
  }
  return { busy, set };
}

export function InternRow({ job, onChange }: { job: any; onChange?: () => void }) {
  const it = job.intern || {};
  const { busy, set } = useInternActions(job, () => onChange?.());
  const [saving, setSaving] = useState(false);
  const out = it.status === "out";
  const fails = (it.checks || []).filter((c: any) => c.state === "fail");
  const warns = (it.checks || []).filter((c: any) => c.state === "warn");
  async function track() { setSaving(true); try { await api("/api/applications", { body: { job_id: job.id } }); onChange?.(); } catch {} setSaving(false); }
  return (
    <div className={`li hover irow ${out ? "out" : ""}`}>
      <CompanyLogo name={job.company} website={job.company_website} size="sm" />
      <div className="grow">
        <div className="row" style={{ gap: ".45rem" }}>
          <Link href={`/jobs/${job.id}`} className="title">{job.title}</Link>
          {job.new && <span className="tag new">New</span>}
        </div>
        <div className="sub">{job.company}{job.deadline ? `, apply by ${day(job.deadline)}` : ""}</div>
        <div className="meta" style={{ marginTop: ".45rem" }}>
          <span className={`tag track ${it.track}`}>{it.track_label}</span>
          <FactChips it={it} />
          {job.application_stage && <span className="tag good">{label(job.application_stage)}</span>}
        </div>
        {out && fails.length > 0 && <div className="why-out"><b>Filtered out:</b> {fails.map((f: any) => f.detail).join(" ")}</div>}
        {!out && warns.length > 0 && <div className="why-out warn">Confirm before applying: {warns.map((w: any) => CHECK_NAME[w.key] || w.label).join(", ")}.</div>}
        {it.note && <div className="why-out">{it.note}</div>}
      </div>
      <div className="end">
        <ScoreChip value={job.score_total} />
        {out ? (
          <>
            {fails.some((f: any) => f.key === "pay") && <button className="btn sm" disabled={busy} onClick={() => set({ paid: true })} title="Use this after the recruiter tells you it's paid">It's paid</button>}
            {!it.overrides?.include && <button className="btn sm quiet" disabled={busy} onClick={() => set({ include: true })} title="Count it even though it missed a rule">Count it anyway</button>}
            <button className="btn sm quiet icon" disabled={busy} onClick={() => set({ hidden: true })} title="Hide" aria-label="Hide"><EyeOff /></button>
          </>
        ) : (
          <>
            {!job.application_stage && <button className="btn sm quiet" onClick={track} disabled={saving}>Save</button>}
            <Link className="btn sm" href={`/apply/${job.id}#recruiter`} title="Find the recruiter and copy a message"><UserSearch />Recruiter</Link>
            <Link className="btn sm primary" href={`/apply/${job.id}`}>Apply</Link>
          </>
        )}
      </div>
    </div>
  );
}

/** The checks, one per rule, with the line from the posting that decided it. */
export function InternChecks({ job, onChange }: { job: any; onChange?: () => void }) {
  const it = job.intern || {};
  const { busy, set } = useInternActions(job, () => onChange?.());
  const ov = it.overrides || {};
  return (
    <section className="panel ichecks">
      <div className="spread" style={{ alignItems: "center", marginBottom: ".6rem" }}>
        <h3>{it.status === "out" ? "Doesn't qualify yet" : it.status === "check" ? "Qualifies, with one thing to confirm" : "Qualifies"}</h3>
        <span className={`tag ${it.status === "out" ? "bad" : it.status === "check" ? "warn" : "good"}`}>{it.track_label}</span>
      </div>
      {(it.checks || []).map((c: any) => {
        const Icon = STATE_ICON[c.state] || Minus;
        const Kind = CHECK_ICON[c.key];
        return (
          <div key={c.key} className={`icheck ${c.state}`}>
            <span className="state"><Icon /></span>
            <div className="grow">
              <div className="row" style={{ gap: ".4rem" }}>{Kind && <Kind className="kind" />}<b>{c.label}</b></div>
              <div className="small">{c.detail}</div>
              {c.evidence && <div className="quote">"{c.evidence}"</div>}
            </div>
          </div>
        );
      })}
      {it.note && <p className="small muted" style={{ marginTop: ".6rem" }}>{it.note}</p>}
      <div className="row" style={{ marginTop: ".8rem" }}>
        {(it.checks || []).some((c: any) => c.key === "pay" && c.state !== "pass") || ov.paid ?
          <button className="btn sm" disabled={busy} onClick={() => set({ paid: !ov.paid })}>{ov.paid ? "Undo: it's paid" : "The recruiter confirmed it's paid"}</button> : null}
        {(it.checks || []).some((c: any) => c.key === "hours" && c.state !== "pass") || ov.hours_ok ?
          <button className="btn sm" disabled={busy} onClick={() => set({ hours_ok: !ov.hours_ok })}>{ov.hours_ok ? "Undo: hours work" : "The hours work for me"}</button> : null}
        {it.status === "out" || ov.include ?
          <button className="btn sm quiet" disabled={busy} onClick={() => set({ include: !ov.include })}>{ov.include ? "Stop counting it" : "Count it anyway"}</button> : null}
      </div>
      {it.sources?.length > 0 && <p className="tiny faint" style={{ marginTop: ".7rem" }}>Found through: {it.sources.join(", ")}.</p>}
    </section>
  );
}

/** Where you are in the spring internship season: hiring runs October to December, the internship January to May. */
export function Season() {
  const start = new Date(2026, 9, 1).getTime(), end = new Date(2027, 5, 1).getTime();
  const pos = (d: Date) => Math.max(0, Math.min(100, (100 * (d.getTime() - start)) / (end - start)));
  const now = pos(new Date());
  const months = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"];
  return (
    <div className="season" aria-label="Spring internship season: apply October to December, intern January to May">
      <div className="bar">
        <span className="seg apply" style={{ left: 0, width: `${pos(new Date(2027, 0, 1))}%` }}><b>Apply</b></span>
        <span className="seg work" style={{ left: `${pos(new Date(2027, 0, 1))}%`, right: 0 }}><b>Internship, 10 to 30 hrs a week</b></span>
        {now > 0 && now < 100 && <span className="now" style={{ left: `${now}%` }}><i>Today</i></span>}
      </div>
      <div className="months">{months.map((m) => <span key={m}>{m}</span>)}</div>
    </div>
  );
}
