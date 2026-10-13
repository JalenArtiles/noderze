/** Visual themes. The choice is stored in this browser (the Noderze window keeps it between launches). */
export type ThemeId = "night" | "pop" | "dusk" | "classic";

export const THEMES: { id: ThemeId; name: string; desc: string; bar: string; font: string; swatch: { nav: string; paper: string; card: string; accent: string; accent2: string; ink: string } }[] = [
  { id: "night", font: '"Unbounded", sans-serif', name: "Night Shift", desc: "Dark console with neon pink and gold.", bar: "#0a0d24",
    swatch: { nav: "#0a0d24", paper: "#0d1130", card: "#1a2150", accent: "#ff4f8b", accent2: "#ffc627", ink: "#eef1fd" } },
  { id: "pop", font: '"Gabarito", sans-serif', name: "Sun Devil Pop", desc: "Maroon and gold, bold outlines, sticker shadows.", bar: "#8c1d40",
    swatch: { nav: "#8c1d40", paper: "#ffe9a8", card: "#ffffff", accent: "#8c1d40", accent2: "#2f5bff", ink: "#1d1033" } },
  { id: "dusk", font: '"Syne", sans-serif', name: "Desert Dusk", desc: "An Arizona sunset behind every page.", bar: "#1e1440",
    swatch: { nav: "#2c1650", paper: "#fbf1f3", card: "#ffffff", accent: "#c2357a", accent2: "#ffb93b", ink: "#24163f" } },
  { id: "classic", font: '"Bricolage Grotesque", sans-serif', name: "Classic", desc: "Light and quiet, navy and maroon.", bar: "#101b30",
    swatch: { nav: "#101b30", paper: "#f4f5f9", card: "#ffffff", accent: "#8c1d40", accent2: "#ffc627", ink: "#141b2d" } },
];

export const DEFAULT_THEME: ThemeId = "night";
const KEY = "noderze-theme";

export function currentTheme(): ThemeId {
  if (typeof document === "undefined") return DEFAULT_THEME;
  const t = document.documentElement.dataset.theme as ThemeId | undefined;
  return THEMES.some((x) => x.id === t) ? (t as ThemeId) : DEFAULT_THEME;
}

export function applyTheme(id: ThemeId) {
  document.documentElement.dataset.theme = id;
  const bar = THEMES.find((t) => t.id === id)?.bar;
  if (bar) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bar);
  try { localStorage.setItem(KEY, id); } catch {}
}

/** Runs before first paint (inlined in the page head) so a saved theme never flashes the default. */
export const THEME_BOOT = `try{var t=localStorage.getItem("${KEY}"),b={${THEMES.map((t) => `${t.id}:"${t.bar}"`).join(",")}};if(t&&b[t]){document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="theme-color"]');if(m)m.setAttribute("content",b[t])}}catch(e){}`;
