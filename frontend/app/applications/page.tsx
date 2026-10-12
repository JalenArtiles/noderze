"use client";
import Link from "next/link";
import { Err, Loading, PageHeader, PathBadge, ScoreChip } from "@/components/ui";
import { api, day, label, useApi } from "@/lib/api";

const HINT: Record<string, string> = { saved: "Roles you saved or opened in Apply", preparing: "Tailoring and drafting", applied: "Follow up about a week after applying",
  interviewing: "Prep lives on each application", offer: "", rejected: "", withdrawn: "" };

export default function Board() {
  const { data, error, reload } = useApi("/api/applications");
  async function move(id: number, stage: string) { await api(`/api/applications/${id}`, { method: "PATCH", body: { stage } }); reload(); }
  return (
    <>
      <PageHeader title="Applications" lede="Every role you're working on, by stage. Moving a card to Applied sets a follow-up reminder." />
      <Err msg={error} />
      {!data ? <Loading /> : <div className="kanban">
        {data.stages.map((s: string) => (
          <div key={s} className="col"><h3>{label(s)}<span className="num">{data.columns[s]?.length || 0}</span></h3>
            {!data.columns[s]?.length && HINT[s] && <div className="hint">{HINT[s]}</div>}
            {data.columns[s]?.map((c: any) => (
              <div key={c.id} className="kcard">
                <div className="tiny muted">{c.company}</div>
                <Link href={`/applications/${c.id}`} style={{ color: "var(--ink)", fontWeight: 650, display: "block", lineHeight: 1.3, margin: ".1rem 0 .4rem" }}>{c.title}</Link>
                <div className="row small"><PathBadge value={c.path_class} />{c.score != null && <ScoreChip value={c.score} />}
                  {c.readiness != null && <span className="muted">{c.readiness}% ready</span>}</div>
                {(c.deadline || c.follow_up_date) && <div className="tiny" style={{ marginTop: ".35rem" }}>{c.deadline ? `Due ${day(c.deadline)}` : ""}{c.deadline && c.follow_up_date ? ", " : ""}{c.follow_up_date ? `follow up ${day(c.follow_up_date)}` : ""}</div>}
                {c.next_action && <div className="tiny muted" style={{ marginTop: ".2rem" }}>{c.next_action}</div>}
                <select value={c.stage} onChange={(e) => move(c.id, e.target.value)} style={{ marginTop: ".5rem", width: "100%", fontSize: ".82rem", padding: ".3rem .4rem" }} aria-label={`Stage for ${c.title}`}>
                  {data.stages.map((x: string) => <option key={x} value={x}>{label(x)}</option>)}</select>
              </div>))}
          </div>))}
      </div>}
    </>
  );
}
