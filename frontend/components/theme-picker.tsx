"use client";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { THEMES, ThemeId, applyTheme, currentTheme } from "@/lib/theme";

/** Four theme cards, each a tiny drawing of the theme. Picking one applies it immediately and remembers it. */
export default function ThemePicker() {
  const [cur, setCur] = useState<ThemeId | null>(null);
  useEffect(() => setCur(currentTheme()), []);
  return (
    <div className="themes" role="radiogroup" aria-label="Theme">
      {THEMES.map((t) => (
        <button key={t.id} type="button" role="radio" aria-checked={cur === t.id} className={`theme-card ${cur === t.id ? "on" : ""}`}
          onClick={() => { applyTheme(t.id); setCur(t.id); }}>
          <span className="theme-mini" style={{ background: t.swatch.paper }} aria-hidden>
            <i className="tm-nav" style={{ background: t.swatch.nav }} />
            <i className="tm-card" style={{ background: t.swatch.card }}>
              <i style={{ background: t.swatch.ink }} /><i style={{ background: t.swatch.ink }} /><i className="tm-btn" style={{ background: t.swatch.accent }} />
            </i>
            <i className="tm-dot" style={{ background: t.swatch.accent2 }} />
          </span>
          <span className="theme-name" style={{ fontFamily: t.font }}>{t.name}{cur === t.id && <Check aria-label="Current theme" />}</span>
          <span className="theme-desc">{t.desc}</span>
        </button>
      ))}
    </div>
  );
}
