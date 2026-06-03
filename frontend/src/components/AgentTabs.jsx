import { useState, useEffect } from 'react';

function AgentTabs({ agentId, status }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  // DevDaily config
  const [ddLang, setDdLang] = useState('');  
  const [ddCount, setDdCount] = useState(5);
  const [ddTopic, setDdTopic] = useState('');

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
  }, [agentId]);

  const handleManualTrigger = async () => {
    setLoading(true);
    try {
      let url = `http://localhost:8000/api/agent/${agentId}/trigger`;
      let opts = { method: 'POST' };
      if (agentId === 'devdaily') {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify({ language: ddLang, count: parseInt(ddCount) || 5, topic: ddTopic });
      }
      await fetch(url, opts);
      setTimeout(fetchData, 3000);
      setTimeout(fetchData, 8000);
      setTimeout(fetchData, 15000);
    } catch(e) {
      console.error(e);
    }
    setLoading(false);
  };

  const renderContent = () => {
    if (!data || Object.keys(data).length === 0) {
      return <div style={{ color: 'var(--text-secondary)' }}>No data available. Click "Manual Run" to fetch data.</div>;
    }

    if (agentId === 'ai_times') {
      const vids = data.videos || { news: [], personality: [] };
      return (
        <div>
          <h3 style={{ margin: '20px 0' }}>AI News (5 Latest)</h3>
          <div className="data-grid">
            {vids.news.map((v, i) => (
              <a key={i} href={v.url} target="_blank" rel="noreferrer" className="glass-panel data-card" style={{textDecoration:'none', color:'inherit'}}>
                <img src={v.thumbnail} alt={v.title} style={{width: '100%', borderRadius: 8, marginBottom: 12}} />
                <h4>{v.title}</h4>
                <p style={{color:'var(--text-secondary)', fontSize:'0.85rem'}}>{v.channel} • {new Date(v.date).toLocaleDateString()}</p>
              </a>
            ))}
          </div>
          <h3 style={{ margin: '20px 0' }}>Personality / Interviews (5 Latest)</h3>
          <div className="data-grid">
            {vids.personality.map((v, i) => (
              <a key={i} href={v.url} target="_blank" rel="noreferrer" className="glass-panel data-card" style={{textDecoration:'none', color:'inherit'}}>
                <img src={v.thumbnail} alt={v.title} style={{width: '100%', borderRadius: 8, marginBottom: 12}} />
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
          <h3>Recent Emails with AI Summaries</h3>
          <div style={{display:'flex', flexDirection:'column', gap: 12, marginTop: 16}}>
            {emails.map((e, i) => (
              <div key={i} className="glass-panel" style={{padding: 16}}>
                <div style={{display:'flex', justifyContent:'space-between', marginBottom: 8}}>
                  <strong>{e.subject} {e.is_key ? '⭐' : ''}</strong>
                  <span style={{color:'var(--accent-color)', fontSize:'0.9rem'}}>{e.category}</span>
                </div>
                <div style={{color:'var(--text-secondary)', fontSize:'0.85rem', marginBottom: 8}}>{e.sender}</div>
                {e.ai_summary && (
                  <div style={{background:'rgba(59,130,246,0.08)', padding:'10px 14px', borderRadius:8, marginBottom:8, borderLeft:'3px solid var(--accent-color)'}}>
                    <span style={{fontSize:'0.8rem', color:'var(--accent-color)', fontWeight:600}}>AI Summary:</span>
                    <p style={{fontSize:'0.9rem', marginTop:4}}>{e.ai_summary}</p>
                  </div>
                )}
                <p style={{fontSize:'0.85rem', color:'var(--text-secondary)'}}>{e.snippet}</p>
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
              <h3 style={{color:'var(--success-color)', marginBottom:12}}>Block 1 — Top 5 Gainers</h3>
              {m.top_gainers?.map(s => (
                <div key={s.symbol} style={{display:'flex', justifyContent:'space-between', marginBottom:8}}>
                  <span>{s.symbol}</span>
                  <span style={{fontWeight: 600}}>${s.price}</span>
                  <span className="positive">+{s.change_pct}%</span>
                </div>
              ))}
            </div>
            <div className="glass-panel" style={{padding: 20}}>
              <h3 style={{color:'var(--danger-color)', marginBottom:12}}>Block 2 — Top 5 Losers</h3>
              {m.top_losers?.map(s => (
                <div key={s.symbol} style={{display:'flex', justifyContent:'space-between', marginBottom:8}}>
                  <span>{s.symbol}</span>
                  <span style={{fontWeight: 600}}>${s.price}</span>
                  <span className="negative">{s.change_pct}%</span>
                </div>
              ))}
            </div>
          </div>

          <div className="glass-panel" style={{padding: 20, marginBottom: 24}}>
            <h3 style={{marginBottom: 12}}>Block 3 — Full Watchlist</h3>
            <table className="watchlist-table">
              <thead>
                <tr><th>Symbol</th><th>Price</th><th>Change</th><th>Change %</th></tr>
              </thead>
              <tbody>
                {m.watchlist?.map(s => (
                  <tr key={s.symbol}>
                    <td style={{fontWeight:600}}>{s.symbol}</td>
                    <td>${s.price}</td>
                    <td className={s.change >= 0 ? 'positive' : 'negative'}>{s.change >= 0 ? '+' : ''}{s.change}</td>
                    <td className={s.change_pct >= 0 ? 'positive' : 'negative'}>{s.change_pct >= 0 ? '+' : ''}{s.change_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="data-grid">
            <div className="glass-panel" style={{padding: 20}}>
              <h3 style={{color:'var(--warning-color)', marginBottom:12}}>Precious Metals</h3>
              {m.metals?.map(s => (
                <div key={s.symbol} style={{display:'flex', justifyContent:'space-between', marginBottom:8}}>
                  <span>{s.symbol === 'GC=F' ? '🥇 Gold' : '🥈 Silver'}</span>
                  <span style={{fontWeight:600}}>${s.price}</span>
                  <span className={s.change_pct >= 0 ? 'positive' : 'negative'}>{s.change_pct >= 0 ? '+' : ''}{s.change_pct}%</span>
                </div>
              ))}
            </div>
            <div className="glass-panel" style={{padding: 20}}>
              <h3 style={{color:'var(--accent-color)', marginBottom:12}}>Currency Pairs</h3>
              {m.currencies?.map(s => (
                <div key={s.symbol} style={{display:'flex', justifyContent:'space-between', marginBottom:8}}>
                  <span>{s.symbol.replace('=X','')}</span>
                  <span style={{fontWeight:600}}>{s.price}</span>
                  <span className={s.change_pct >= 0 ? 'positive' : 'negative'}>{s.change_pct >= 0 ? '+' : ''}{s.change_pct}%</span>
                </div>
              ))}
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
                    <span style={{float:'right'}}>⭐ {r.stars?.toLocaleString()}</span>
                    {r.language && <span style={{fontSize:'0.75rem', background:'rgba(255,255,255,0.08)', padding:'2px 8px', borderRadius:12, marginLeft:8}}>{r.language}</span>}
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

  const title = agentId.replaceAll('_', ' ').replace(/\b\w/g, l => l.toUpperCase());

  return (
    <div className="fade-in">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ fontSize: '2rem' }}>{title}</h2>
        <div style={{display:'flex', gap: 16, alignItems:'center'}}>
          {status && <span style={{color:'var(--text-secondary)'}}>Status: {status.status}{status.last_run ? ` • Last: ${new Date(status.last_run).toLocaleTimeString()}` : ''}</span>}
          <button className="btn" onClick={handleManualTrigger} disabled={loading || (status && status.status === 'running')}>
            {loading ? 'Triggering...' : 'Manual Run'}
          </button>
        </div>
      </div>

      {agentId === 'devdaily' && (
        <div className="glass-panel" style={{padding: 20, marginBottom: 24}}>
          <h3 style={{marginBottom: 12}}>Configuration</h3>
          <div className="config-form">
            <div>
              <label className="config-label">Language Filter</label>
              <input className="config-input" placeholder="e.g. python, javascript" value={ddLang} onChange={e => setDdLang(e.target.value)} />
            </div>
            <div>
              <label className="config-label">Number of Results</label>
              <input className="config-input" type="number" min="1" max="25" value={ddCount} onChange={e => setDdCount(e.target.value)} />
            </div>
            <div>
              <label className="config-label">Topic / Keyword</label>
              <input className="config-input" placeholder="e.g. AI, web dev" value={ddTopic} onChange={e => setDdTopic(e.target.value)} />
            </div>
          </div>
        </div>
      )}
      
      {renderContent()}
    </div>
  );
}

export default AgentTabs;
