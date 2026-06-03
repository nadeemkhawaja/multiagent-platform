import { useState, useEffect } from 'react';
import OrchestratorDashboard from './components/OrchestratorDashboard';
import AgentTabs from './components/AgentTabs';

function App() {
  const [activeTab, setActiveTab] = useState('orchestrator');
  const [agentsStatus, setAgentsStatus] = useState({});

  useEffect(() => {
    // Poll agent status every 5 seconds
    const fetchStatus = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/system/agents');
        const data = await res.json();
        setAgentsStatus(data);
      } catch (err) {
        console.error("Failed to fetch agent status", err);
      }
    };
    
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const renderContent = () => {
    if (activeTab === 'orchestrator') {
      return <OrchestratorDashboard agentsStatus={agentsStatus} />;
    }
    return <AgentTabs agentId={activeTab} status={agentsStatus[activeTab]} />;
  };

  return (
    <div className="app-container">
      <nav className="sidebar">
        <h1>AutoSchedule OS</h1>
        
        <button 
          className={`nav-btn ${activeTab === 'orchestrator' ? 'active' : ''}`}
          onClick={() => setActiveTab('orchestrator')}
        >
          <span className="icon">📊</span>
          Main Orchestrator
        </button>
        
        <div style={{ margin: '20px 0', borderBottom: '1px solid var(--border-color)' }}></div>
        
        <button 
          className={`nav-btn ${activeTab === 'ai_times' ? 'active' : ''}`}
          onClick={() => setActiveTab('ai_times')}
        >
          <span className="icon">📰</span>
          AI-Times
          {agentsStatus.ai_times && (
            <span className={`status-indicator status-${agentsStatus.ai_times.status}`} style={{marginLeft: 'auto'}}></span>
          )}
        </button>
        
        <button 
          className={`nav-btn ${activeTab === 'mailman' ? 'active' : ''}`}
          onClick={() => setActiveTab('mailman')}
        >
          <span className="icon">✉️</span>
          Mailman
          {agentsStatus.mailman && (
            <span className={`status-indicator status-${agentsStatus.mailman.status}`} style={{marginLeft: 'auto'}}></span>
          )}
        </button>
        
        <button 
          className={`nav-btn ${activeTab === 'wallstreet_wolf' ? 'active' : ''}`}
          onClick={() => setActiveTab('wallstreet_wolf')}
        >
          <span className="icon">📈</span>
          Wallstreet Wolf
          {agentsStatus.wallstreet_wolf && (
            <span className={`status-indicator status-${agentsStatus.wallstreet_wolf.status}`} style={{marginLeft: 'auto'}}></span>
          )}
        </button>

        <button 
          className={`nav-btn ${activeTab === 'devdaily' ? 'active' : ''}`}
          onClick={() => setActiveTab('devdaily')}
        >
          <span className="icon">💻</span>
          DevDaily
          {agentsStatus.devdaily && (
            <span className={`status-indicator status-${agentsStatus.devdaily.status}`} style={{marginLeft: 'auto'}}></span>
          )}
        </button>
      </nav>
      
      <main className="main-content">
        {renderContent()}
      </main>
    </div>
  );
}

export default App;
