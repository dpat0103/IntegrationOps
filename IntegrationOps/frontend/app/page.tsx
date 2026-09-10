const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getJSON(path:string){
  const res = await fetch(`${API}${path}`, {cache:"no-store"});
  if(!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export default async function Home(){
  const [overview,status] = await Promise.all([getJSON("/api/overview"),getJSON("/api/status")]);
  return <main style={{maxWidth:1100,margin:"0 auto",padding:32}}>
    <h1>IntegrationOps</h1>
    <p style={{color:"#96a0b5"}}>Backend-first reliability monitoring dashboard.</p>
    <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(160px,1fr))",gap:12}}>
      {[["Integrations",overview.total_integrations],["Healthy",overview.healthy],["Degraded",overview.degraded],["Down",overview.down],["Incidents",overview.active_incidents],["Availability",overview.availability_24h ? `${overview.availability_24h}%` : "—"]].map(([k,v])=><div key={k as string} style={{padding:18,border:"1px solid #26304a",borderRadius:12,background:"#12192b"}}><div style={{color:"#96a0b5",fontSize:13}}>{k}</div><div style={{fontSize:28,fontWeight:700}}>{v}</div></div>)}
    </div>
    <section style={{marginTop:24,padding:18,border:"1px solid #26304a",borderRadius:12,background:"#12192b"}}>
      <h2>Integrations</h2>
      {status.map((s:any)=><div key={s.id} style={{padding:"12px 0",borderTop:"1px solid #26304a"}}><strong>{s.name}</strong> · {s.status} · {s.latency_ms ?? "—"} ms<div style={{color:"#96a0b5",fontSize:13}}>{s.failure_type ?? "No active failure"}</div></div>)}
    </section>
  </main>
}
