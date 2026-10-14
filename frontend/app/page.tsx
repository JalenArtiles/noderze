"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, Backpack, Briefcase, GraduationCap, Globe, MapPin, Shield, Sun, TrendingUp } from "lucide-react";
import { Callout, Err, JobList, PathBadge, SectionHead } from "@/components/ui";
import { CompanyLogo, RouteArt, ScoreRing } from "@/components/visual";
import { useApi } from "@/lib/api";

const TILE_ICON: Record<string, any> = { interns: Backpack, programs: GraduationCap, az: Sun, socal: MapPin, remote: Globe, cyber: Shield, goal: TrendingUp };

export default function Home() {
  const { data, error } = useApi("/api/home");
  const [greet, setGreet] = useState("Hello");
  useEffect(() => { const h = new Date().getHours(); setGreet(h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"); }, []);
  const best = data?.best;
  const setupNeeded = data && (!data.status.llm || data.status.search_provider === "none");
  return (
    <>
      <Err msg={error} />
      <section className="hero">
        <RouteArt />
        <div className="grid">
          <div>
            <h1>{greet}{data?.name ? `, ${data.name}` : ""}.</h1>
            <p className="sub">{data ? `${data.totals.jobs} roles across ${data.totals.companies} companies, rescanned every three hours. Here's where to start.` : "Loading your matches..."}</p>
            <div className="row" style={{ marginTop: "1.1rem" }}>
              <Link className="btn gold" href="/companies">Browse companies hiring</Link>
              <Link className="btn on-dark" href="/opportunities">All roles</Link>
            </div>
          </div>
          {best && (
            <div className="bestmove">
              <span className="tag"><ArrowUpRight />Your best move</span>
              <div className="row" style={{ marginTop: ".75rem", flexWrap: "nowrap", alignItems: "flex-start", gap: ".8rem" }}>
                <CompanyLogo name={best.company} website={best.company_website} size="lg" />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="small muted">{best.company}</div>
                  <h3 style={{ fontSize: "1.12rem", margin: ".1rem 0 .35rem" }}>{best.title}</h3>
                  <div className="row small"><PathBadge value={best.path_class} /><span className="muted">{best.location_text}</span></div>
                </div>
                <ScoreRing value={best.score_total} />
              </div>
              <p className="small muted" style={{ margin: ".7rem 0 .8rem" }}>{best.score_breakdown?.career_path?.reasons?.[0]?.replace(/^\w+: /, "")}</p>
              <div className="row"><Link className="btn primary sm" href={`/apply/${best.id}`}>Apply</Link>
                <Link className="btn sm" href={`/jobs/${best.id}`}>See why it fits</Link></div>
            </div>)}
        </div>
      </section>

      {setupNeeded && <div style={{ marginTop: "1rem" }}><Callout action={<Link href="/settings#connections">Finish setup</Link>}>
        Job scans work. Web research, people search and smarter writing switch on when you add a search provider and an Anthropic key.</Callout></div>}

      <div className="sec">
        <SectionHead title="Explore" />
        <div className="tiles">
          {data?.tiles.map((t: any) => { const Icon = TILE_ICON[t.key] || Briefcase; return (
            <Link key={t.key} href={t.href} className={`tile ${t.tone}`}>
              <span className="top"><span className="icon"><Icon /></span><span className="count num">{t.count}</span></span>
              <b>{t.label}</b><span className="hint">{t.hint}</span></Link>); })}
        </div>
      </div>

      <div className="split sec">
        <div>
          <SectionHead title="Top matches" aside={<Link href="/opportunities">All roles</Link>} />
          {data && <JobList jobs={data.top} page={6} />}
        </div>
        <div className="stack-lg">
          <section className="panel">
            <h3 style={{ marginBottom: ".7rem" }}>Do this today</h3>
            {!data?.today?.length ? <p className="small muted">Nothing urgent. Browse companies or apply to your best move.</p> :
              <ol className="todo">{data.today.map((a: any, i: number) => (
                <li key={i}><div><Link href={a.link} style={{ fontWeight: 600 }}>{a.text}</Link><div className="small muted">{a.why}</div></div></li>))}</ol>}
          </section>
          <section className="panel">
            <div className="spread" style={{ marginBottom: ".7rem" }}><h3>Your applications</h3><Link className="small" href="/applications">Open board</Link></div>
            <div className="pipe">{data && Object.entries(data.pipeline).map(([k, v]: any) => <Link key={k} href="/applications"><b className="num">{v}</b><span>{k}</span></Link>)}</div>
            {data?.next_moves?.length > 0 && <div style={{ marginTop: ".9rem" }}>{data.next_moves.slice(0, 3).map((m: any, i: number) => (
              <div key={i} className="fact"><Link href={m.link} style={{ fontWeight: 600 }}>{m.text}</Link><div className="small muted">{m.why}</div></div>))}</div>}
          </section>
        </div>
      </div>
    </>
  );
}
