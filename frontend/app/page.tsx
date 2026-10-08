"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, Briefcase, Building2, GraduationCap, Globe, MapPin, Shield, Sun, TrendingUp } from "lucide-react";
import { Err, PathBadge } from "@/components/ui";
import { CAT_LABEL } from "@/components/ui";
import { CompanyLogo, RouteArt, ScoreRing } from "@/components/visual";
import { useApi } from "@/lib/api";

const TILE_ICON: Record<string, any> = { programs: GraduationCap, az: Sun, socal: MapPin, remote: Globe, cyber: Shield, goal: TrendingUp };

export default function Home() {
  const { data, error, reload } = useApi("/api/home");
  const [greet, setGreet] = useState("Hello");
  useEffect(() => { const h = new Date().getHours(); setGreet(h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"); }, []);
  const best = data?.best;
  return (
    <>
      <Err msg={error} />
      <section className="hero">
        <RouteArt />
        <div className="grid">
          <div>
            <h1>{greet}{data?.name ? `, ${data.name}` : ""}.</h1>
            <p className="sub">{data ? `Entry sales roles at cybersecurity companies with real SE teams, in Arizona, remote or Southern California. ${data.totals.companies} companies watched, scanned every three hours.` : "Loading your matches..."}</p>
            <div className="row" style={{ marginTop: ".9rem", alignItems: "flex-start" }}>
              <Link className="btn gold" href="/companies">See companies hiring</Link>
              <Link className="btn ghost" href="/companies">Browse companies</Link>
            </div>
          </div>
          {best && (
            <div className="bestmove">
              <span className="tag"><ArrowUpRight size={14} />Your best move</span>
              <div className="row" style={{ marginTop: ".7rem", flexWrap: "nowrap", alignItems: "flex-start" }}>
                <CompanyLogo name={best.company} website={best.company_website} size="lg" />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="small muted">{best.company}</div>
                  <h3 style={{ fontSize: "1.15rem", margin: ".1rem 0 .3rem" }}>{best.title}</h3>
                  <div className="row small"><PathBadge value={best.path_class} /><span className="muted">{best.location_text}</span></div>
                </div>
                <ScoreRing value={best.score_total} size="lg" />
              </div>
              <p className="small muted" style={{ margin: ".6rem 0" }}>{best.score_breakdown?.career_path?.reasons?.[0]}</p>
              <div className="row"><Link className="btn primary small" href={`/apply/${best.id}`}>Apply</Link>
                <Link className="btn secondary small" href={`/jobs/${best.id}`}>See why it fits</Link></div>
            </div>)}
        </div>
      </section>
      {data && (!data.status.llm || data.status.search_provider === "none") && (
        <div className="notice" style={{ marginBottom: "1rem" }}>Job board scans work now. Deep research and recruiter discovery need a search provider, and smarter writing needs an Anthropic key. Add them in backend/.env when you're ready.</div>)}

      <h2>Explore by interest</h2>
      <div className="tiles">
        {data?.tiles.map((t: any) => { const Icon = TILE_ICON[t.key] || Briefcase; return (
          <Link key={t.key} href={t.href} className={`tile ${t.tone}`}><span className="icon"><Icon /></span><span className="count num">{t.count}</span><b>{t.label}</b><span>{t.hint}</span></Link>); })}
      </div>

      <div className="spread" style={{ alignItems: "baseline" }}><h2>Top matches for you</h2><Link href="/opportunities" className="small">See all <ArrowUpRight size={13} /></Link></div>
      <div className="grid3">
        {data?.top.map((j: any) => (
          <Link key={j.id} href={`/apply/${j.id}`} className={`card mini ${j.category}`}>
            <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
              <CompanyLogo name={j.company} website={j.company_website} />
              <div style={{ flex: 1, minWidth: 0 }}><div className="cat">{CAT_LABEL[j.category]}</div><b style={{ display: "block", lineHeight: 1.25 }}>{j.title}</b><span className="small muted">{j.company}</span></div>
              <ScoreRing value={j.score_total} />
            </div>
            <div className="row small"><PathBadge value={j.path_class} /><span className="muted"><MapPin size={12} /> {j.location_text}</span></div>
          </Link>))}
        {data && !data.top.length && <div className="panel empty">No matches yet. Click Refresh now at the top right.</div>}
      </div>

      <div className="grid2" style={{ marginTop: "1.6rem" }}>
        <section className="panel"><h2 style={{ marginTop: 0 }}>Do this today</h2>
          {!data?.today?.length && <p className="muted">Nothing urgent.</p>}
          <ol className="today">{data?.today?.map((a: any, i: number) => (
            <li key={i}><span className="n">{i + 1}</span><div><Link href={a.link}><b>{a.text}</b></Link><div className="small muted">{a.why}</div></div></li>))}</ol>
        </section>
        <section className="panel"><h2 style={{ marginTop: 0 }}>Your pipeline</h2>
          <div className="pipe">{data && Object.entries(data.pipeline).map(([k, v]: any) => <Link key={k} href="/applications" style={{ color: "inherit" }}><div><b className="num">{v}</b><span>{k}</span></div></Link>)}</div>
          <h3 style={{ marginTop: "1.1rem" }}>Next moves</h3>
          {data?.next_moves?.map((m: any, i: number) => <div key={i} className="fact"><Link href={m.link}>{m.text}</Link><div className="small muted">{m.why}</div></div>)}
          <div className="row" style={{ marginTop: ".8rem" }}><Link className="btn secondary small" href="/companies"><Building2 size={15} />Companies</Link>
            <Link className="btn secondary small" href="/resume">Resume</Link><Link className="btn secondary small" href="/skills">Skills roadmap</Link></div>
        </section>
      </div>
    </>
  );
}
