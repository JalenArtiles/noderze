"use client";
import Link from "next/link";
import { Err, PathBadge } from "@/components/ui";
import { api, day, label, useApi } from "@/lib/api";

export default function Board() {
  const { data, error, reload } = useApi("/api/applications");
  async function move(id: number, stage: string) { await api(`/api/applications/${id}`, { method: "PATCH", body: { stage } }); reload(); }
  return (
    <>
      <h1>Applications</h1>
      <p className="muted">Move a card with its stage menu. Moving to Applied sets a follow-up reminder.</p>
      <Err msg={error} />
      <div className="kanban">
        {data?.stages.map((s: string) => (
          <div key={s} className="col"><h3>{label(s)}<span className="muted num">{data.columns[s]?.length || 0}</span></h3>
            {data.columns[s]?.map((c: any) => (
              <div key={c.id} className="card" style={{ padding: ".6rem .7rem" }}>
                <div className="small muted">{c.company}</div>
                <Link href={`/applications/${c.id}`}><b className="small">{c.title}</b></Link>
                <div className="row small" style={{ marginTop: ".25rem" }}><PathBadge value={c.path_class} />{c.score != null && <span className="num">{Math.round(c.score)}</span>}
                  {c.readiness != null && <span className="muted">Ready {c.readiness}%</span>}</div>
                {c.deadline && <div className="small">Due {day(c.deadline)}</div>}
                {c.follow_up_date && <div className="small">Follow up {day(c.follow_up_date)}</div>}
                {c.next_action && <div className="small muted">{c.next_action}</div>}
                <select value={c.stage} onChange={(e) => move(c.id, e.target.value)} style={{ marginTop: ".35rem", width: "100%" }} aria-label="Stage">
                  {data.stages.map((x: string) => <option key={x} value={x}>{label(x)}</option>)}</select>
              </div>))}
          </div>))}
      </div>
    </>
  );
}
