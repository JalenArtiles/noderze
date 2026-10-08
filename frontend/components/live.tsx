"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Bell, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

/** Live bar: polls for new data every minute, refreshes open pages automatically, and offers a manual refresh. */
export default function LiveBar() {
  const [u, setU] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [ago, setAgo] = useState("");
  const since = useRef<string>(new Date(Date.now() - 60_000).toISOString().replace("Z", ""));
  const lastRun = useRef<string | null>(null);
  const firstBuild = useRef<string | null>(null);
  async function poll() {
    try {
      const d = await api(`/api/updates?since=${encodeURIComponent(since.current)}`);
      const finished = d.last_run?.finished_at || null;
      if ((d.new_jobs > 0) || (finished && lastRun.current && finished !== lastRun.current)) window.dispatchEvent(new Event("noderze:data"));
      if (d.new_jobs > 0) since.current = d.now;
      lastRun.current = finished;
      setU(d);
      setBusy(d.running > 0);
      const b = d.app_update?.build_id || null;
      if (b && !firstBuild.current) firstBuild.current = b;
      // A new version of the interface was just swapped in: load it.
      if (d.app_update?.state === "done" && b && firstBuild.current && b !== firstBuild.current) window.location.reload();
    } catch {}
  }
  const active = busy || ["building", "swapping"].includes(u?.app_update?.state);
  useEffect(() => { poll(); const t = setInterval(poll, active ? 10_000 : 60_000); return () => clearInterval(t); }, [active]);
  useEffect(() => {
    const tick = () => {
      const f = u?.last_run?.finished_at; if (!f) return setAgo("not yet");
      const m = Math.round((Date.now() - new Date(f + "Z").getTime()) / 60000);
      setAgo(m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`);
    };
    tick(); const t = setInterval(tick, 30_000); return () => clearInterval(t);
  }, [u]);
  async function refresh() {
    setBusy(true);
    try {
      const { run_id } = await api("/api/workflows/discover_jobs", { body: {} });
      let r: any;
      do { await new Promise((ok) => setTimeout(ok, 3000)); r = await api(`/api/runs/${run_id}`); window.dispatchEvent(new Event("noderze:data")); } while (r.status === "running");
    } catch {}
    await poll(); setBusy(false);
  }
  const upd = u?.app_update;
  return (
    <div className="livebar">
      {(upd?.state === "building" || upd?.state === "swapping") && <span className="badge new">Updating Noderze, about 2 minutes. It reloads on its own.</span>}
      {upd?.state === "failed" && <span className="badge warn" title={upd.error || ""}>An update didn't apply. Noderze is still running the previous version.</span>}
      <span className={`dot ${busy ? "busy" : ""}`} aria-hidden />
      <span className="small">{busy ? "Scanning job boards..." : `Live. Last scan ${ago}`}</span>
      {u?.unseen > 0 && <Link href="/opportunities?new=1" className="pill"><Bell size={13} />{u.unseen} new</Link>}
      <button className="btn secondary small" onClick={refresh} disabled={busy}><RefreshCw size={14} />Refresh now</button>
    </div>
  );
}
