import { useState, useEffect } from 'react';

function OrchestratorDashboard({ agentsStatus }) {
  const [resources, setResources] = useState(null);

  useEffect(() => {
    const fetchResources = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/system/resources');
        const data = await res.json();
        setResources(data);
      } catch (err) {
        console.error("Failed to fetch resources", err);
      }
    };
    
    fetchResources();
    const interval = setInterval(fetchResources, 2000);
    return () => clearInterval(interval);
  }, []);

  const getBarColor = (pct) => {
    if (pct > 90) return 'var(--danger-color)';
    if (pct > 70) return 'var(--warning-color)';
    return 'var(--success-color)';
  };

  const handleRestartAgent = async (agentName) => {
    try {
      await fetch(`http://localhost:8000/api/agent/${agentName}/trigger`, { method: 'POST' });
    } catch (err) {
      console.error(err);
    }
  };

  if (!resources) return <div className="glass-panel" style={{padding: 20}}>Loading system metrics...</div>;

  const alarms = resources.alarms || [];

  return (
    <div className="fade-in">
      <h2 style={{ marginBottom: 24, fontSize: '2rem' }}>Main Orchestrator</h2>
      
      {alarms.length > 0 && (
        <div className="alarm-banner">
          <span style={{ fontSize: '1.5rem' }}>⚠️</span>
          <div>
            <strong>CRITICAL ALARM — Resource threshold exceeded!</strong>
            {alarms.map((a, i) => (
              <div key={i} className="alarm-detail">
                <span>🔴 {a.resource}: {a.value}%</span>
                <span style={{color: 'var(--text-secondary)'}}>→ {a.suggestion}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="gauges-grid">
        {[
          { label: 'CPU Usage', value: resources.cpu_percent, unit: '%' },
          { label: 'RAM Usage', value: resources.ram_percent, unit: '%' },
          { label: 'Disk Usage', value: resources.disk_percent, unit: '%' },
          { label: 'Active Threads', value: resources.active_threads, unit: '' },
        ].map((g, i) => (
          <div key={i} className="glass-panel gauge-card">
            <div className="gauge-label">{g.label}</div>
            <div className="gauge-value" style={{ color: (g.unit === '%' && g.value > 90) ? 'var(--danger-color)' : 'var(--text-primary)' }}>
              {g.value}{g.unit}
            </div>
            {g.unit === '%' && (
              <div className="progress-bar-bg">
                <div className="progress-bar-fill" style={{ width: `${Math.min(g.value, 100)}%`, background: getBarColor(g.value) }}></div>
              </div>
            )}
          </div>
        ))}
      </div>

      <h3 style={{ marginBottom: 16 }}>Agent Status</h3>
      <div className="data-grid">
        {Object.entries(agentsStatus).map(([id, info]) => (
          <div key={id} className="glass-panel data-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <strong style={{ textTransform: 'capitalize' }}>{id.replaceAll('_', ' ')}</strong>
              <span className={`status-indicator status-${info.status}`}></span>
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              Status: {info.status}
              {info.last_run && <div style={{marginTop: 4}}>Last run: {new Date(info.last_run).toLocaleString()}</div>}
              {info.error && <div style={{color: 'var(--danger-color)', marginTop: 8}}>Error: {info.error}</div>}
            </div>
            {info.status === 'error' && (
              <button className="btn" style={{marginTop: 12, fontSize: '0.85rem', padding: '6px 14px'}} onClick={() => handleRestartAgent(id)}>Restart Agent</button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default OrchestratorDashboard;
