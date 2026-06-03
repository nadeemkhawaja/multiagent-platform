import { useState, useEffect } from 'react';

function AgentTabs({ agentId, status }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    try {
      const res = await fetch(`http://localhost:8000/api/agent/${agentId}/data`);
      const result = await res.json();
      setData(result);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchData();
    // No automatic polling here, manual refresh button provided
  }, [agentId]);

  const handleManualTrigger = async () => {
    setLoading(true);
    try {
      await fetch(`http://localhost:8000/api/agent/${agentId}/trigger`, { method: 'POST' });
      // Poll a few times after trigger
      setTimeout(fetchData, 3000);
      setTimeout(fetchData, 8000);
    } catch(e) {
      console.error(e);
    }
    setLoading(false);
  };

  const renderContent = () => {
    if (!data || Object.keys(data).length === 0) {
      return <div style={{ color: 'var(--text-secondary)' }}>No data available. Run the agent first.</div>;
    }

    if (agentId === 'ai_times') {
      const vids = data.videos || { news: [], personality: [] };
      return (
        <div>
          <h3 style={{ margin: '20px 0' }}>AI News</h3>
          <div className="data-grid">
            {vids.news.map((v, i) => (
              <a key={i} href={v.url} target="_blank" rel="noreferrer" className="glass-panel data-card" style={{textDecoration:'none', color:'inherit'}}>
                <img src={v.thumbnail} alt="thumb" style={{width: '100%', borderRadius: 8, marginBottom: 12}} />
                <h4>{v.title}</h4>
                <p style={{color:'var(--text-secondary)', fontSize:'0.85rem'}}>{v.channel} • {new Date(v.date).toLocaleDateString()}</p>
              </a>
            ))}
          </div>

          <h3 style={{ margin: '20px 0' }}>Personality Interviews</h3>
          <div className="data-grid">
            {vids.personality.map((v, i) => (
              <a key={i} href={v.url} target="_blank" rel="noreferrer" className="glass-panel data-card" style={{textDecoration:'none', color:'inherit'}}>
                <img src={v.thumbnail} alt="thumb" style={{width: '100%', borderRadius: 8, marginBottom: 12}} />
                <h4>{v.title}</h4>
                <p style={{color:'var(--text-secondary)', fontSize:'0.85rem'}}>{v.channel} • {new Date(v.date).toLocaleDateString()}</p>
              </a>
            ))}
          </div>
        </div>
      );
    }

    if (agentId === 'mailman') {
      const breakdown = data.emails?.breakdown || {};
      const emails = data.emails?.emails || [];
      return (
        <div>
          <div className="glass-panel" style={{padding: 20, marginBottom: 24}}>
            <h3>Category Breakdown</h3>
            <ul style={{listStyle:'none', marginTop: 12, display:'flex', gap: 16, flexWrap: 'wrap'}}>
              {Object.entries(breakdown).map(([cat, count]) => (
                <li key={cat} style={{background:'rgba(255,255,255,0.05)', padding:'8px 16px', borderRadius:20}}>
                  {cat}: <strong>{count}</strong>
                </li>
              ))}
            </ul>
          </div>

          <h3>Recent Emails</h3>
          <div style={{display:'flex', flexDirection:'column', gap: 12, marginTop: 16}}>
            {emails.map((e, i) => (
              <div key={i} className="glass-panel" style={{padding: 16}}>
                <div style={{display:'flex', justifyContent:'space-between', marginBottom: 8}}>
                  <strong>{e.subject} {e.is_key ? '⭐' : ''}</strong>
                  <span style={{color:'var(--accent-color)', fontSize:'0.9rem'}}>{e.category}</span>
                </div>
                <div style={{color:'var(--text-secondary)', fontSize:'0.85rem', marginBottom: 8}}>{e.sender}</div>
                <p style={{fontSize:'0.9rem'}}>{e.snippet}</p>
              </div>
            ))}
          </div>
        </div>
      );
    }

    if (agentId === 'wallstreet_wolf') {
      const m = data.market_data || {};
      return (
        <div>
          {m.commentary && (
            <div className="glass-panel" style={{padding: 24, marginBottom: 24, background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--accent-color)'}}>
              <h3 style={{marginBottom: 12}}>LLM Market Commentary</h3>
              <p style={{fontStyle:'italic'}}>{m.commentary}</p>
            </div>
          )}
          
          <div className="data-grid" style={{marginBottom: 24}}>
            <div className="glass-panel" style={{padding: 20}}>
              <h3 style={{color:'var(--success-color)', marginBottom:12}}>Top 5 Gainers</h3>
              {m.top_gainers?.map(s => <div key={s.symbol} style={{display:'flex', justifyContent:'space-between', marginBottom:8}}><span>{s.symbol}</span><span>+{s.change_pct}%</span></div>)}
            </div>
            <div className="glass-panel" style={{padding: 20}}>
              <h3 style={{color:'var(--danger-color)', marginBottom:12}}>Top 5 Losers</h3>
              {m.top_losers?.map(s => <div key={s.symbol} style={{display:'flex', justifyContent:'space-between', marginBottom:8}}><span>{s.symbol}</span><span>{s.change_pct}%</span></div>)}
            </div>
            <div className="glass-panel" style={{padding: 20}}>
              <h3 style={{color:'var(--warning-color)', marginBottom:12}}>Metals & Forex</h3>
              {m.metals?.map(s => <div key={s.symbol} style={{display:'flex', justifyContent:'space-between', marginBottom:8}}><span>{s.symbol}</span><span>{s.price}</span></div>)}
              <hr style={{borderColor:'var(--border-color)', margin:'12px 0'}}/>
              {m.currencies?.map(s => <div key={s.symbol} style={{display:'flex', justifyContent:'space-between', marginBottom:8}}><span>{s.symbol}</span><span>{s.price}</span></div>)}
            </div>
          </div>
        </div>
      );
    }

    if (agentId === 'devdaily') {
      const d = data.digest || {};
      return (
        <div>
          {d.llm_summary && (
            <div className="glass-panel" style={{padding: 24, marginBottom: 24, background: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--success-color)'}}>
              <h3 style={{marginBottom: 12}}>LLM Daily Summary</h3>
              <p>{d.llm_summary}</p>
            </div>
          )}

          <div className="data-grid">
            <div className="glass-panel" style={{padding: 20}}>
              <h3 style={{marginBottom: 16}}>GitHub Trending</h3>
              <div style={{display:'flex', flexDirection:'column', gap:16}}>
                {d.github_repos?.map((r, i) => (
                  <div key={i}>
                    <a href={r.url} target="_blank" rel="noreferrer" style={{color:'var(--accent-color)', textDecoration:'none', fontWeight:'bold'}}>{r.name}</a>
                    <span style={{float:'right'}}>⭐ {r.stars}</span>
                    <p style={{fontSize:'0.85rem', color:'var(--text-secondary)', marginTop:4}}>{r.description}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="glass-panel" style={{padding: 20}}>
              <h3 style={{marginBottom: 16}}>Dev.to Articles</h3>
              <div style={{display:'flex', flexDirection:'column', gap:16}}>
                {d.devto_articles?.map((a, i) => (
                  <div key={i}>
                    <a href={a.url} target="_blank" rel="noreferrer" style={{color:'var(--warning-color)', textDecoration:'none', fontWeight:'bold'}}>{a.title}</a>
                    <span style={{float:'right'}}>❤️ {a.reactions}</span>
                    <p style={{fontSize:'0.85rem', color:'var(--text-secondary)', marginTop:4}}>{a.description}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      );
    }
  };

  const title = agentId.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());

  return (
    <div className="fade-in">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ fontSize: '2rem' }}>{title}</h2>
        <div style={{display:'flex', gap: 16, alignItems:'center'}}>
          {status && <span style={{color:'var(--text-secondary)'}}>Status: {status.status}</span>}
          <button className="btn" onClick={handleManualTrigger} disabled={loading || (status && status.status === 'running')}>
            {loading ? 'Triggering...' : 'Manual Run'}
          </button>
        </div>
      </div>
      
      {renderContent()}
    </div>
  );
}

export default AgentTabs;
