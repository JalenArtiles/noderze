"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Backpack, Briefcase, Mail } from "lucide-react";
import { Empty, Err, Loading, PageHeader, PathBadge, ScoreChip, stageLabel } from "@/components/ui";
import { CompanyLogo } from "@/components/visual";
import { api, day, useApi } from "@/lib/api";

const KINDS: [string, string, any][] = [["all", "All", null], ["career", "Career roles", Briefcase], ["internship", "Spring internships", Backpack]];
const ALWAYS = ["started", "applied", "talking", "interviewing"];

function remembered(key: string, fallback: string) {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}
function remember(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch {}
}

export default function Board() {
  const { data, error, reload } = useApi("/api/applications");
  const replies = useApi("/api/replies");
  const [kind, setKind] = useState("all");
  const [drafts, setDrafts] = useState(false);
  useEffect(() => { setKind(remembered("noderze.apps.kind", "all")); setDrafts(remembered("noderze.apps.drafts", "0") === "1"); }, []);
  const pick = (k: string) => { setKind(k); remember("noderze.apps.kind", k); };
  const toggleDrafts = (v: boolean) => { setDrafts(v); remember("noderze.apps.drafts", v ? "1" : "0"); };
  async function move(id: number, stage: string) { await api(`/api/applications/${id}`, { method: "PATCH", body: { stage } }); reload(); }

  const cards: any[] = data?.cards || [];
  const ofKind = (k: string) => cards.filter((c) => k === "all" || c.kind === k);
  const shown = ofKind(kind);
  const groups: any[] = (data?.groups || []).filter((g: any) => g.key !== "saved" || drafts);
  const inGroup = (g: any) => shown.filter((c) => g.stages.includes(c.stage));
  const savedCount = shown.filter((c) => (data?.groups?.[0]?.stages || []).includes(c.stage)).length;
  const onBoard = shown.length - savedCount;
  const unread: Record<number, number> = {};
  for (const r of replies.data?.items || []) if (!r.seen && r.needs_you && r.application_id) unread[r.application_id] = (unread[r.application_id] || 0) + 1;

  return (
    <>
      <PageHeader title="Applications"
        lede="Roles you started or applied to. Opening Apply to read a posting or your tailored resume doesn't add a role here; opening the company's application does." />
      <Err msg={error} />
      {!data ? <Loading /> : <>
        <div className="toolbar">
          <div className="chips">
            {KINDS.map(([k, l, Icon]) => (
              <button key={k} className={`chip ${kind === k ? "on" : ""}`} onClick={() => pick(k)}>{Icon && <Icon />}{l}
                <span className="n num">{ofKind(k).filter((c) => !(data.groups[0].stages as string[]).includes(c.stage)).length}</span></button>))}
          </div>
          <label className="check" style={{ marginLeft: "auto" }}><input type="checkbox" checked={drafts} onChange={(e) => toggleDrafts(e.target.checked)} />
            Show saved and drafts{savedCount ? ` (${savedCount})` : ""}</label>
        </div>
        {!onBoard && !drafts ? (
          <div className="panel"><Empty title={kind === "internship" ? "No internship applications yet" : kind === "career" ? "No career applications yet" : "No applications yet"}
            action={<Link className="btn primary" href={kind === "internship" ? "/internships" : "/opportunities"}>{kind === "internship" ? "Find internships" : "Browse roles"}</Link>}>
            Click Apply on a role, then Open the application. It shows up here as Started, and moves to Applied when you click I applied.
            {savedCount ? ` You also have ${savedCount} saved or drafted ${savedCount === 1 ? "role" : "roles"}; tick Show saved and drafts to see them.` : ""}</Empty></div>
        ) : (
          <div className="kanban">
            {groups.filter((g) => ALWAYS.includes(g.key) || g.key === "saved" || inGroup(g).length).map((g) => (
              <div key={g.key} className={`col ${g.key}`}><h3>{g.label}<span className="num">{inGroup(g).length}</span></h3>
                {!inGroup(g).length && g.hint && <div className="hint">{g.hint}</div>}
                {inGroup(g).map((c) => (
                  <div key={c.id} className="kcard">
                    <div className="row" style={{ gap: ".45rem", flexWrap: "nowrap" }}>
                      <CompanyLogo name={c.company} website={c.company_website} size="sm" />
                      <span className="tiny muted" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.company}</span>
                      {unread[c.id] > 0 && <Link href="/replies" className="tag new" style={{ marginLeft: "auto" }} title="New email from this company"><Mail size={12} />{unread[c.id]}</Link>}
                    </div>
                    <Link href={`/applications/${c.id}`} className="ktitle">{c.title}</Link>
                    <div className="row small">{c.is_intern ? <span className="tag track network">Spring internship</span> : <PathBadge value={c.path_class} />}{c.score != null && <ScoreChip value={c.score} />}
                      {c.readiness != null && <span className="muted">{c.readiness}% ready</span>}</div>
                    {(c.date_applied || c.deadline || c.follow_up_date) && <div className="tiny" style={{ marginTop: ".35rem" }}>
                      {[c.date_applied ? `Applied ${day(c.date_applied)}` : c.deadline ? `Due ${day(c.deadline)}` : "", c.follow_up_date ? `follow up ${day(c.follow_up_date)}` : ""].filter(Boolean).join(", ")}</div>}
                    {c.next_action && <div className="tiny muted" style={{ marginTop: ".2rem" }}>{c.next_action}</div>}
                    <select value={c.stage} onChange={(e) => move(c.id, e.target.value)} className="kstage" aria-label={`Stage for ${c.title}`}>
                      {data.stages.filter((x: string) => x !== "researching" || x === c.stage).map((x: string) => <option key={x} value={x}>{stageLabel(x)}</option>)}</select>
                  </div>))}
              </div>))}
          </div>)}
      </>}
    </>
  );
}
