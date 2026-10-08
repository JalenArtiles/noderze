"use client";
import { useCallback, useEffect, useState } from "react";

export const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const TOKEN = process.env.NEXT_PUBLIC_AGENT_TOKEN || "";

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData } = {}): Promise<T> {
  const method = opts.method || (opts.body !== undefined || opts.form ? "POST" : "GET");
  const res = await fetch(BASE + path, {
    method,
    headers: { ...(opts.form ? {} : { "Content-Type": "application/json" }), "X-Agent-Token": TOKEN },
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    cache: "no-store",
  });
  if (!res.ok) {
    let msg: any = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).detail ?? msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export function useApi<T = any>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try { setData(await api<T>(path)); setError(null); }
    catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, [path]);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {  // live updates: refetch whenever the live bar reports new data
    const h = () => reload();
    window.addEventListener("noderze:data", h);
    return () => window.removeEventListener("noderze:data", h);
  }, [reload]);
  return { data, error, loading, reload, setData };
}

export const fileUrl = (path: string) => `${BASE}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(TOKEN)}`;
export const money = (n?: number | null) => (n == null ? "" : `$${Math.round(n).toLocaleString()}`);
export const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "");
export const label = (s?: string | null) => (s || "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
