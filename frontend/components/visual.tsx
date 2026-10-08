"use client";
import { useState } from "react";

const PALETTE = ["#8c1d40", "#2563eb", "#0d9488", "#7c3aed", "#d97706", "#0f766e", "#be185d", "#334155"];
const hash = (s: string) => Array.from(s || "?").reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);

/** Company logo from the company's own site favicon (via Google's favicon service), with a colored initials fallback. */
export function CompanyLogo({ name, website, size = "md" }: { name: string; website?: string | null; size?: "md" | "lg" }) {
  const [failed, setFailed] = useState(false);
  let domain = "";
  try { domain = website ? new URL(website.startsWith("http") ? website : `https://${website}`).hostname.replace(/^www\./, "") : ""; } catch {}
  const cls = `logo ${size === "lg" ? "lg" : ""}`;
  if (!domain || failed) {
    const initials = (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
    return <span className={`${cls} initials`} style={{ background: PALETTE[hash(name) % PALETTE.length] }} aria-hidden>{initials}</span>;
  }
  return <span className={cls}><img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=128`} alt="" onError={() => setFailed(true)} /></span>;
}

export function ScoreRing({ value, size = "md" }: { value: number; size?: "md" | "lg" }) {
  const v = Math.max(0, Math.min(100, Math.round(value || 0)));
  const px = size === "lg" ? 84 : 64, stroke = size === "lg" ? 8 : 7, r = (px - stroke) / 2, c = 2 * Math.PI * r;
  const color = v >= 75 ? "#16a34a" : v >= 60 ? "#f59e0b" : "#94a3b8";
  return (
    <div className={`ring ${size === "lg" ? "lg" : ""}`} title={`Fit score ${v} out of 100`}>
      <svg width={px} height={px}><circle cx={px / 2} cy={px / 2} r={r} stroke="#e8ebf2" strokeWidth={stroke} fill="none" />
        <circle cx={px / 2} cy={px / 2} r={r} stroke={color} strokeWidth={stroke} fill="none" strokeLinecap="round" strokeDasharray={`${(c * v) / 100} ${c}`} /></svg>
      <b className="num">{v}</b>
    </div>
  );
}

/** Original hero illustration: a route of stops climbing toward a gold destination. */
export function RouteArt({ className = "art" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 420 220" fill="none" aria-hidden>
      <path d="M10 200 C 80 190, 90 120, 150 130 S 230 170, 260 110 S 330 40, 400 30" stroke="rgba(255,198,39,.35)" strokeWidth="18" strokeLinecap="round" />
      <path d="M10 200 C 80 190, 90 120, 150 130 S 230 170, 260 110 S 330 40, 400 30" stroke="#ffc627" strokeWidth="5" strokeLinecap="round" strokeDasharray="1 14" />
      {[[40, 194], [150, 130], [260, 110]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r="9" fill="#fff" stroke="#ffc627" strokeWidth="5" />)}
      <circle cx="392" cy="32" r="18" fill="#ffc627" /><circle cx="392" cy="32" r="30" stroke="rgba(255,198,39,.4)" strokeWidth="3" />
      <text x="300" y="80" fill="rgba(255,255,255,.75)" fontSize="13" fontFamily="sans-serif">Sales Engineer</text>
    </svg>
  );
}
