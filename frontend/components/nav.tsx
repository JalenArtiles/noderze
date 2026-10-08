"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Building2, Compass, FileText, GraduationCap, House, Settings, ShieldCheck, SquareKanban, TrendingUp, Users } from "lucide-react";

const GROUPS: [string, [string, string, any][]][] = [
  ["Discover", [["/", "Home", House], ["/companies", "Companies", Building2], ["/opportunities", "All roles", Compass], ["/programs", "ASE and SE programs", GraduationCap]]],
  ["Apply", [["/applications", "Applications", SquareKanban], ["/resume", "Resume", FileText], ["/contacts", "Contacts", Users], ["/approvals", "Approvals", ShieldCheck]]],
  ["Grow", [["/skills", "Skills roadmap", TrendingUp], ["/settings", "Settings", Settings]]],
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="nav" aria-label="Main">
      <Link href="/" className="brand"><img src="/icon-192.png" alt="" /><div><b>Noderze</b><span>Cyber sales to Sales Engineering</span></div></Link>
      {GROUPS.map(([g, links]) => (
        <div key={g}><div className="group">{g}</div>
          {links.map(([href, l, Icon]) => (
            <Link key={href} href={href} className={`link ${(href === "/" ? path === "/" : path.startsWith(href)) ? "active" : ""}`}><Icon aria-hidden />{l}</Link>))}
        </div>))}
    </nav>
  );
}
