"use client";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, CheckCircle2, ChevronRight, Info, Loader2, Minus, X } from "lucide-react";
import { api } from "@/lib/api";

/* Workflow runs (full company analysis, deep research, job scans...) are shown in one place: a side panel
   that lists the planned steps as a route, each closed with a one-line result, and leads with the outcome
   once the run finishes. Detail lines stay one click away instead of filling the page. */

type Step = { title: string; status: string; summary?: string | null; warnings: string[]; lines: string[]; started?: string | null; finished?: string | null };
type View = { title: string; steps: Step[]; progress: { done: number; total: number }; highlights: any[]; notices: any[] };
type Run = { id: number; kind: string; subject?: string | null; status: string; error?: string | null; started_at: string; finished_at?: string | null; view: View };
type Item = { key: string; runId: number; label: string; quiet?: boolean; run?: Run };
type StartOpts = { kind: string; body?: any; label: string; key?: string; quiet?: boolean; onDone?: (run: Run) => void };

const Ctx = createContext<{ start: (o: StartOpts) => Promise<number>; isRunning: (key: string) => boolean; show: (runId: number) => void } | null>(null);

export function useActivity() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useActivity must be used inside ActivityProvider");
  return c;
}

export function ActivityProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [pillHidden, setPillHidden] = useState(false);
  const callbacks = useRef(new Map<number, ((r: Run) => void) | undefined>());

  const start = useCallback(async ({ kind, body, label, key, quiet, onDone }: StartOpts) => {
    const { run_id } = await api(`/api/workflows/${kind}`, { body: body || {} });
    callbacks.current.set(run_id, onDone);
    const k = key || `${kind}:${JSON.stringify(body || {})}`;
    setItems((prev) => [{ key: k, runId: run_id, label, quiet }, ...prev.filter((x) => x.key !== k && x.runId !== run_id)].slice(0, 6));
    setPillHidden(false);
    if (!quiet) setOpen(run_id);
    return run_id;
  }, []);

  useEffect(() => {
    const live = items.filter((i) => !i.run || i.run.status === "running");
    if (!live.length) return;
    const t = setTimeout(async () => {
      const got = (await Promise.all(live.map((i) => api<Run>(`/api/runs/${i.runId}`).catch(() => null)))).filter(Boolean) as Run[];
      setItems((prev) => prev.map((i) => ({ ...i, run: got.find((g) => g.id === i.runId) || i.run })));
      for (const r of got) {
        if (r.status !== "running" && callbacks.current.has(r.id)) {
          const cb = callbacks.current.get(r.id);
          callbacks.current.delete(r.id);
          cb?.(r);
          window.dispatchEvent(new Event("noderze:data"));
        }
      }
    }, 1200);
    return () => clearTimeout(t);
  }, [items]);

  const isRunning = useCallback((key: string) => items.some((i) => i.key === key && (!i.run || i.run.status === "running")), [items]);
  const show = useCallback((runId: number) => setOpen(runId), []);
  const current = items.find((i) => i.runId === open);
  const latest = items[0];

  return (
    <Ctx.Provider value={{ start, isRunning, show }}>
      {children}
      {current && <Panel item={current} onClose={() => setOpen(null)} />}
      {!current && latest && !pillHidden && <Pill item={latest} onOpen={() => setOpen(latest.runId)} onDismiss={() => setPillHidden(true)} />}
    </Ctx.Provider>
  );
}

function Pill({ item, onOpen, onDismiss }: { item: Item; onOpen: () => void; onDismiss: () => void }) {
  const r = item.run;
  const running = !r || r.status === "running";
  const p = r?.view.progress;
  const cur = r?.view.steps.find((s) => s.status === "running");
  return (
    <div className="row" style={{ position: "fixed", right: "1.2rem", bottom: "1.2rem", zIndex: 45, gap: ".4rem" }}>
      <button className={`act-pill ${running ? "running" : ""}`} onClick={onOpen} aria-live="polite">
        {running ? <Loader2 /> : r?.status === "failed" ? <AlertTriangle /> : <CheckCircle2 />}
        <span>{item.label}</span>
        <span className="sub">{running ? (p && p.total > 1 ? `${cur ? cur.title : "Starting"}, ${p.done + 1} of ${p.total}` : "Working") : r?.status === "failed" ? "Stopped. See why" : "Done. See results"}</span>
      </button>
      {!running && <button className="btn icon sm" onClick={onDismiss} aria-label="Dismiss"><X /></button>}
    </div>
  );
}

function elapsed(a?: string | null, b?: string | null) {
  if (!a) return "";
  const ms = (b ? new Date(b).getTime() : Date.now()) - new Date(a).getTime();
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

function Panel({ item, onClose }: { item: Item; onClose: () => void }) {
  const r = item.run;
  const running = !r || r.status === "running";
  const v = r?.view;
  const pct = v ? Math.round((100 * v.progress.done) / Math.max(1, v.progress.total)) : 4;
  const [showSteps, setShowSteps] = useState(false);
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const stepsVisible = running || showSteps || r?.status === "failed";
  return (
    <aside className="act" role="dialog" aria-label={`${v?.title || "Run"}: ${item.label}`}>
      <div className="act-head">
        <div className="spread" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
          <div style={{ minWidth: 0 }}><div className="kind">{v?.title || "Starting"}</div><h2>{item.label}</h2></div>
          <button className="btn icon quiet" onClick={onClose} aria-label="Close panel"><X /></button>
        </div>
        {running ? <>
          <div className="small muted" style={{ marginTop: ".5rem" }}>{v ? `Step ${Math.min(v.progress.done + 1, v.progress.total)} of ${v.progress.total}` : "Starting"}. You can keep using Noderze; this keeps running.</div>
          <div className="progress"><i style={{ width: `${Math.max(pct, 4)}%` }} /></div>
        </> : r?.status === "failed" ? (
          <div className="callout bad" style={{ marginTop: ".8rem" }}><AlertTriangle /><div className="grow">This run stopped early. The failed step below says why.</div></div>
        ) : (
          <div className="done-banner" style={{ marginTop: ".6rem" }}><CheckCircle2 />Finished in {elapsed(r?.started_at, r?.finished_at)}</div>
        )}
      </div>
      <div className="act-body">
        {!running && v && <>
          {v.highlights.length > 0 && <div className="hl">{v.highlights.map((h: any, i: number) => {
            const wide = typeof h.value === "string" && h.value.length > 8;
            const inner = <><b className="num">{h.value}</b><span>{h.label}{h.detail ? `, ${h.detail}` : ""}</span></>;
            return h.href ? <Link key={i} href={h.href} className={wide ? "wide" : ""} onClick={onClose}>{inner}</Link> : <div key={i} className={wide ? "wide" : ""}>{inner}</div>;
          })}</div>}
          {v.notices.map((n: any, i: number) => (
            <div key={i} className={`callout ${n.level === "warn" ? "warn" : ""}`} style={{ marginBottom: ".6rem" }}>
              {n.level === "warn" ? <AlertTriangle /> : <Info />}
              <div className="grow">{n.text}{n.action && <> <Link href={n.action.href} onClick={onClose}>{n.action.label}</Link></>}</div>
            </div>))}
          {r?.status !== "failed" && <button className="btn quiet sm" style={{ margin: ".4rem 0 .6rem -.5rem" }} onClick={() => setShowSteps(!showSteps)} aria-expanded={showSteps}>
            <ChevronRight style={{ transform: showSteps ? "rotate(90deg)" : "none" }} />{showSteps ? "Hide steps" : `Show the ${v.steps.length} ${v.steps.length === 1 ? "step" : "steps"}`}</button>}
        </>}
        {stepsVisible && v && <ol className="route-steps">{v.steps.map((s, i) => <StepItem key={i} s={s} />)}</ol>}
        {!v && <p className="muted small">Starting...</p>}
      </div>
    </aside>
  );
}

function StepItem({ s }: { s: Step }) {
  const [open, setOpen] = useState(false);
  const icon = s.status === "done" ? <Check /> : s.status === "running" ? <Loader2 /> : s.status === "skipped" ? <Minus /> : s.status === "failed" ? <X /> : null;
  const details = s.lines.filter((l) => !s.warnings.includes(l));
  return (
    <li className={s.status}>
      <span className="ic" aria-hidden>{icon}</span>
      <div className="t">{s.title}<span className="sr">, {s.status.replace("_", " ")}</span></div>
      {s.summary && <div className="s">{s.summary}</div>}
      {s.status === "running" && !s.summary && details.length > 0 && <div className="s">{details[details.length - 1]}</div>}
      {(details.length > 0 || s.warnings.length > 0) && s.status !== "running" && <>
        <button className="det" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide details" : s.warnings.length ? `Details (${s.warnings.length} ${s.warnings.length === 1 ? "warning" : "warnings"})` : "Details"}</button>
        {open && <div className="lines">{s.warnings.map((l, i) => <div key={`w${i}`} style={{ color: "var(--amber)" }}>{l}</div>)}{details.map((l, i) => <div key={i}>{l}</div>)}</div>}
      </>}
    </li>
  );
}
