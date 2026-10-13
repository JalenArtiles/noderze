"use client";
import { useEffect } from "react";
import { THEMES, currentTheme } from "@/lib/theme";

/** Keeps the window's title bar color in step with the saved theme. */
export default function ThemeSync() {
  useEffect(() => {
    const bar = THEMES.find((t) => t.id === currentTheme())?.bar;
    if (bar) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bar);
  }, []);
  return null;
}
