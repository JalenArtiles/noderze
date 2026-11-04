"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Backpack, Building2, Compass, FileText, GraduationCap, House, Mail, Settings, ShieldCheck, SquareKanban, TrendingUp, Users } from "lucide-react";

const GROUPS: [string, [string, string, any][]][] = [
  ["Discover", [["/", "Home", House], ["/companies", "Companies", Building2], ["/opportunities", "All roles", Compass], ["/programs", "ASE and SE programs", GraduationCap], ["/internships", "Spring internships", Backpack]]],
  ["Apply", [["/applications", "Applications", SquareKanban], ["/replies", "Replies", Mail], ["/resume", "Resume", FileText], ["/contacts", "Contacts", Users], ["/approvals", "Approvals", ShieldCheck]]],
  ["Grow", [["/skills", "Skills roadmap", TrendingUp], ["/settings", "Settings", Settings]]],
];

export default function Nav() {
  const path = usePathname();
  // The live bar polls for updates every minute and shares the counts it gets.
  const [counts, setCounts] = useState<Record<string, number>>({});
  useEffect(() => {
    const on = (e: Event) => setCounts((c) => ({ ...c, ...(e as CustomEvent).detail }));
    window.addEventListener("noderze:counts", on);
    return () => window.removeEventListener("noderze:counts", on);
  }, []);
  const badge: Record<string, number> = { "/replies": counts.replies || 0 };
  return (
    <nav className="nav" aria-label="Main">
      <Link href="/" className="brand"><img src="/icon-192.png" alt="" /><div><b>Noderze</b><span>Your route to Sales Engineering</span></div></Link>
      {GROUPS.map(([g, links]) => (
        <div key={g}><div className="group">{g}</div>
          {links.map(([href, l, Icon]) => (
            <Link key={href} href={href} className={`link ${(href === "/" ? path === "/" : path.startsWith(href)) ? "active" : ""}`}><Icon aria-hidden />{l}
              {badge[href] > 0 && <span className="badge" aria-label={`${badge[href]} new`}>{badge[href]}</span>}</Link>))}
        </div>))}
    </nav>
  );
}
