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
    const interval = setInterval(fetchResources, 2000); // <= 5s update
    return () => clearInterval(interval);
  }, []);

  if (!resources) return <div className="glass-panel" style={{padding: 20}}>Loading system metrics...</div>;

  return (
    <div className="fade-in">
      <h2 style={{ marginBottom: 24, fontSize: '2rem' }}>Main Orchestrator</h2>
      
      {resources.alarm && (
        <div className="alarm-banner">
          <span style={{ fontSize: '1.5rem' }}>⚠️</span>
          <div>
            <strong>CRITICAL ALARM:</strong> System resource usage exceeded 90%. 
            <br/>
            <small>Suggested action: Check background processes or restart crashed agents.</small>
          </div>
        </div>
      )}

      <div className="gauges-grid">
        <div className="glass-panel gauge-card">
          <div className="gauge-label">CPU Usage</div>
          <div className="gauge-value" style={{ color: resources.cpu_percent > 90 ? 'var(--danger-color)' : 'var(--text-primary)'}}>
            {resources.cpu_percent}%
          </div>
        </div>
        
        <div className="glass-panel gauge-card">
          <div className="gauge-label">RAM Usage</div>
          <div className="gauge-value" style={{ color: resources.ram_percent > 90 ? 'var(--danger-color)' : 'var(--text-primary)'}}>
            {resources.ram_percent}%
          </div>
        </div>
        
        <div className="glass-panel gauge-card">
          <div className="gauge-label">Disk Usage</div>
          <div className="gauge-value" style={{ color: resources.disk_percent > 90 ? 'var(--danger-color)' : 'var(--text-primary)'}}>
            {resources.disk_percent}%
          </div>
        </div>
        
        <div className="glass-panel gauge-card">
          <div className="gauge-label">Active Threads</div>
          <div className="gauge-value">{resources.active_threads}</div>
        </div>
      </div>

      <h3 style={{ marginBottom: 16 }}>Agent Status</h3>
      <div className="data-grid">
        {Object.entries(agentsStatus).map(([id, info]) => (
          <div key={id} className="glass-panel data-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <strong style={{ textTransform: 'capitalize' }}>{id.replace('_', ' ')}</strong>
              <span className={`status-indicator status-${info.status}`}></span>
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              Status: {info.status}
              {info.error && <div style={{color: 'var(--danger-color)', marginTop: 8}}>Error: {info.error}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default OrchestratorDashboard;
