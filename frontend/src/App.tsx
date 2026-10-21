import { useState, useEffect, useRef } from 'react';
import { 
  Shield, 
  Terminal, 
  Cpu, 
  BookOpen, 
  CheckCircle2, 
  Clock, 
  AlertTriangle, 
  XCircle, 
  Play, 
  RefreshCw, 
  FileCode, 
  Database, 
  Radio, 
  Layers, 
  StopCircle,
  LogOut,
  User as UserIcon,
  Sparkles
} from 'lucide-react';
import { api, clearStoredToken } from './api';
import type { User, TaskSummary, InvestigationReport } from './api';

export function App() {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authName, setAuthName] = useState('');
  const [authError, setAuthError] = useState<string | null>(null);

  // Task Submission State
  const [objective, setObjective] = useState('');
  const [repositoryUrl, setRepositoryUrl] = useState('https://github.com/fastapi/fastapi');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Active Task & Tasks List
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<TaskSummary | null>(null);
  const [report, setReport] = useState<InvestigationReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  // SSE Live Logs
  const [liveEvents, setLiveEvents] = useState<Array<{ id: number; event: string; payload: any; time: string }>>([]);
  const [sseConnected, setSseConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Fetch initial profile and task list
  useEffect(() => {
    fetchProfile();
    fetchTasks();
    const interval = setInterval(fetchTasks, 6000);
    return () => clearInterval(interval);
  }, []);

  const fetchProfile = async () => {
    try {
      const user = await api.getMe();
      setCurrentUser(user);
    } catch {
      setCurrentUser(null);
    }
  };

  const fetchTasks = async () => {
    try {
      const list = await api.listTasks();
      setTasks(list);
      if (list.length > 0 && !activeTaskId) {
        selectTask(list[0].id);
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Switch active task and load details
  const selectTask = async (taskId: string) => {
    setActiveTaskId(taskId);
    setReport(null);
    setReportError(null);
    setLiveEvents([]);

    try {
      const task = await api.getTask(taskId);
      setActiveTask(task);
      if (task.status === 'completed' || task.status === 'blocked') {
        loadReport(taskId);
      }
    } catch (err: any) {
      console.error(err);
    }
  };

  const loadReport = async (taskId: string) => {
    setReportLoading(true);
    setReportError(null);
    try {
      const rep = await api.getTaskReport(taskId);
      setReport(rep);
    } catch (err: any) {
      setReportError(err.message || 'Report not available');
    } finally {
      setReportLoading(false);
    }
  };

  // SSE streaming listener for active task
  useEffect(() => {
    if (!activeTaskId) return;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const sseUrl = api.getEventSourceUrl(activeTaskId);
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    es.onopen = () => {
      setSseConnected(true);
    };

    const handleEvent = (type: string, dataStr: string) => {
      try {
        const payload = JSON.parse(dataStr);
        setLiveEvents((prev) => [
          ...prev,
          {
            id: payload.id || Date.now(),
            event: type,
            payload,
            time: new Date().toLocaleTimeString(),
          },
        ]);

        if (type === 'status_change') {
          setActiveTask((prev) => prev ? { ...prev, status: payload.status } : null);
          fetchTasks();
          if (payload.status === 'completed' || payload.status === 'blocked') {
            loadReport(activeTaskId);
          }
        }
      } catch (e) {
        console.error(e);
      }
    };

    es.addEventListener('status_change', (e: MessageEvent) => handleEvent('status_change', e.data));
    es.addEventListener('jev_triage', (e: MessageEvent) => handleEvent('jev_triage', e.data));
    es.addEventListener('evidence_collected', (e: MessageEvent) => handleEvent('evidence_collected', e.data));
    es.addEventListener('report_generated', (e: MessageEvent) => handleEvent('report_generated', e.data));
    es.addEventListener('obsidian_synced', (e: MessageEvent) => handleEvent('obsidian_synced', e.data));
    es.addEventListener('close', () => {
      es.close();
      setSseConnected(false);
    });

    es.onerror = () => {
      setSseConnected(false);
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
      setSseConnected(false);
    };
  }, [activeTaskId]);

  const handleSubmitTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!objective.trim() || !repositoryUrl.trim()) return;

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      const res = await api.submitTask(objective, repositoryUrl);
      setObjective('');
      await fetchTasks();
      selectTask(res.task_id);
    } catch (err: any) {
      setSubmitError(err.message || 'Submission failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancelTask = async () => {
    if (!activeTaskId) return;
    try {
      await api.cancelTask(activeTaskId);
      await fetchTasks();
      const updated = await api.getTask(activeTaskId);
      setActiveTask(updated);
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError(null);
    try {
      if (authMode === 'login') {
        const res = await api.login(authEmail, authPassword);
        setCurrentUser(res.user);
      } else {
        const res = await api.register(authEmail, authPassword, authName);
        setCurrentUser(res.user);
      }
      setShowAuthModal(false);
      fetchTasks();
    } catch (err: any) {
      setAuthError(err.message || 'Authentication failed');
    }
  };

  const handleLogout = () => {
    clearStoredToken();
    setCurrentUser(null);
    fetchProfile();
    fetchTasks();
  };

  const getStatusBadge = (status?: string) => {
    switch (status) {
      case 'completed':
        return <span className="badge badge-completed"><CheckCircle2 size={12} /> Completed</span>;
      case 'planning':
        return <span className="badge badge-planning"><Cpu size={12} /> Planning (Jev)</span>;
      case 'executing':
        return <span className="badge badge-executing"><FileCode size={12} /> Executing</span>;
      case 'verifying':
        return <span className="badge badge-verifying"><Sparkles size={12} /> Verifying (AI)</span>;
      case 'blocked':
        return <span className="badge badge-blocked"><AlertTriangle size={12} /> Blocked</span>;
      case 'failed':
        return <span className="badge badge-failed"><XCircle size={12} /> Failed</span>;
      case 'cancelled':
        return <span className="badge badge-received"><StopCircle size={12} /> Cancelled</span>;
      default:
        return <span className="badge badge-received"><Clock size={12} /> Queued</span>;
    }
  };

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto', padding: '1.5rem 2rem' }}>
      {/* Top Navbar */}
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: '1.5rem', borderBottom: '1px solid var(--border-subtle)', marginBottom: '2rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.875rem' }}>
          <div style={{ width: '42px', height: '42px', borderRadius: '12px', background: 'var(--accent-gradient)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 20px rgba(6, 182, 212, 0.4)' }}>
            <Shield size={24} color="#fff" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <h1 style={{ fontSize: '1.5rem', fontWeight: 800, background: 'linear-gradient(90deg, #fff 0%, #94a3b8 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                HAWK
              </h1>
              <span style={{ fontSize: '0.6875rem', fontWeight: 600, padding: '0.125rem 0.5rem', borderRadius: '4px', background: 'rgba(6, 182, 212, 0.15)', color: 'var(--accent-cyan)', border: '1px solid rgba(6, 182, 212, 0.3)' }}>
                v0.1.0 PROD
              </span>
            </div>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-dim)' }}>
              Autonomous Engineering Investigation Platform
            </p>
          </div>
        </div>

        {/* Subsystem Health Status Tags */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', fontSize: '0.75rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.03)', padding: '0.375rem 0.875rem', borderRadius: 'var(--radius-full)', border: '1px solid var(--border-subtle)' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <Database size={13} color="#10b981" /> PostgreSQL
            </span>
            <span style={{ color: 'var(--border-subtle)' }}>•</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <Radio size={13} color="#06b6d4" /> Redis Queue
            </span>
            <span style={{ color: 'var(--border-subtle)' }}>•</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <Cpu size={13} color="#8b5cf6" /> Jev Triage
            </span>
            <span style={{ color: 'var(--border-subtle)' }}>•</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <BookOpen size={13} color="#ec4899" /> Obsidian Memory
            </span>
          </div>

          {/* User Controls */}
          {currentUser ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255,255,255,0.05)', padding: '0.375rem 0.875rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <UserIcon size={14} color="var(--accent-cyan)" />
                <span style={{ fontSize: '0.8125rem', fontWeight: 500 }}>{currentUser.name}</span>
                <span style={{ fontSize: '0.6875rem', color: 'var(--accent-violet)', textTransform: 'uppercase', fontWeight: 600 }}>{currentUser.role}</span>
              </div>
              <button className="btn btn-secondary" onClick={handleLogout} title="Log Out" style={{ padding: '0.5rem 0.75rem' }}>
                <LogOut size={15} />
              </button>
            </div>
          ) : (
            <button className="btn btn-primary" onClick={() => setShowAuthModal(true)}>
              <UserIcon size={15} /> Sign In / Register
            </button>
          )}
        </div>
      </header>

      {/* Main Grid: Left Column (Submission & History), Right Column (Live Monitor & Report) */}
      <div style={{ display: 'grid', gridTemplateColumns: '420px 1fr', gap: '1.75rem', alignItems: 'start' }}>
        
        {/* Left Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          {/* Investigation Launch Card */}
          <div className="glass-panel" style={{ padding: '1.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
              <Terminal size={18} color="var(--accent-cyan)" />
              <h2 style={{ fontSize: '1.0625rem', fontWeight: 700 }}>Initiate Investigation</h2>
            </div>

            <form onSubmit={handleSubmitTask}>
              <div className="input-group">
                <label className="input-label">GitHub Repository URL</label>
                <input
                  type="url"
                  className="input-field"
                  placeholder="https://github.com/owner/repo"
                  value={repositoryUrl}
                  onChange={(e) => setRepositoryUrl(e.target.value)}
                  required
                />
              </div>

              <div className="input-group">
                <label className="input-label">Investigation Objective</label>
                <textarea
                  className="input-field"
                  placeholder="Describe the defect, performance latency, memory leak, or security issue to investigate..."
                  value={objective}
                  onChange={(e) => setObjective(e.target.value)}
                  required
                />
              </div>

              {/* Preset quick buttons */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem', marginBottom: '1.25rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.6875rem', padding: '0.25rem 0.5rem' }}
                  onClick={() => setObjective('Investigate connection timeouts in async client connection pool')}
                >
                  ⚡ Async Connection Timeout
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.6875rem', padding: '0.25rem 0.5rem' }}
                  onClick={() => setObjective('Audit security risks and input validation in user authentication endpoints')}
                >
                  🔒 Auth Security Audit
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.6875rem', padding: '0.25rem 0.5rem' }}
                  onClick={() => setObjective('Detect memory leaks and unbounded buffer growth in worker message processing')}
                >
                  📈 Memory Leak Analysis
                </button>
              </div>

              {submitError && (
                <div style={{ background: 'rgba(239, 68, 68, 0.1)', color: '#f87171', border: '1px solid rgba(239, 68, 68, 0.2)', padding: '0.625rem', borderRadius: 'var(--radius-md)', fontSize: '0.8125rem', marginBottom: '1rem' }}>
                  {submitError}
                </div>
              )}

              <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <RefreshCw size={16} className="pulse-indicator" /> Submitting to Queue...
                  </>
                ) : (
                  <>
                    <Play size={16} fill="currentColor" /> Dispatch Bounded Investigation
                  </>
                )}
              </button>
            </form>

            <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', fontSize: '0.6875rem', color: 'var(--text-dim)' }}>
              <span>Bound: 300 KB / 30 Files</span>
              <span>Jev System One Triage</span>
              <span>Obsidian Memory</span>
            </div>
          </div>

          {/* Investigation History / Task Queue */}
          <div className="glass-panel" style={{ padding: '1.5rem', maxHeight: '520px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Layers size={18} color="var(--accent-violet)" />
                <h2 style={{ fontSize: '1.0625rem', fontWeight: 700 }}>Task Queue & History</h2>
              </div>
              <button className="btn btn-secondary" style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }} onClick={fetchTasks} title="Refresh tasks">
                <RefreshCw size={12} />
              </button>
            </div>

            <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.625rem', paddingRight: '0.25rem' }}>
              {tasks.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '2rem 1rem', color: 'var(--text-dim)', fontSize: '0.875rem' }}>
                  No investigations recorded yet. Submit your first task above.
                </div>
              ) : (
                tasks.map((t) => {
                  const isSelected = t.id === activeTaskId;
                  return (
                    <div
                      key={t.id}
                      onClick={() => selectTask(t.id)}
                      style={{
                        padding: '0.875rem',
                        borderRadius: 'var(--radius-md)',
                        background: isSelected ? 'rgba(6, 182, 212, 0.1)' : 'rgba(255,255,255,0.02)',
                        border: isSelected ? '1px solid rgba(6, 182, 212, 0.4)' : '1px solid var(--border-subtle)',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.375rem' }}>
                        <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                          {t.repository_url.replace('https://github.com/', '')}
                        </span>
                        {getStatusBadge(t.status)}
                      </div>
                      <p style={{ fontSize: '0.8125rem', color: 'var(--text-main)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {t.objective}
                      </p>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '0.5rem', fontSize: '0.6875rem', color: 'var(--text-dim)' }}>
                        <span>{new Date(t.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                        {t.evidence_stats && (
                          <span>{t.evidence_stats.files_retrieved} files ({Math.round(t.evidence_stats.total_evidence_bytes / 1024)} KB)</span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Live Pipeline Monitor & Investigation Report */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          {activeTask ? (
            <>
              {/* Pipeline Stepper & Live Execution Monitor */}
              <div className="glass-panel" style={{ padding: '1.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
                      <h2 style={{ fontSize: '1.25rem', fontWeight: 800 }}>{activeTask.objective}</h2>
                      {getStatusBadge(activeTask.status)}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '0.25rem', fontSize: '0.8125rem', color: 'var(--text-dim)' }}>
                      <span>Repository: <strong>{activeTask.repository_url}</strong></span>
                      <span>•</span>
                      <span>ID: <code style={{ fontFamily: 'var(--font-mono)' }}>{activeTask.id.slice(0, 8)}</code></span>
                      <span>•</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span className="pulse-indicator" style={{ background: sseConnected ? '#10b981' : '#f59e0b' }} />
                        SSE {sseConnected ? 'Connected' : 'Idle'}
                      </span>
                    </div>
                  </div>

                  {activeTask.status !== 'completed' && activeTask.status !== 'failed' && activeTask.status !== 'blocked' && activeTask.status !== 'cancelled' && (
                    <button className="btn btn-danger" onClick={handleCancelTask} style={{ fontSize: '0.8125rem' }}>
                      <StopCircle size={15} /> Cancel Task
                    </button>
                  )}
                </div>

                {/* Multi-stage pipeline visualizer */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '0.5rem', marginBottom: '1.25rem' }}>
                  {[
                    { key: 'received', label: '1. Queued', desc: 'PostgreSQL record' },
                    { key: 'planning', label: '2. Triage', desc: 'Jev System One' },
                    { key: 'executing', label: '3. Evidence', desc: 'GitHub retrieval' },
                    { key: 'verifying', label: '4. Reasoning', desc: 'OpenAI analysis' },
                    { key: 'completed', label: '5. Memory', desc: 'Obsidian sync' },
                  ].map((step) => {
                    const statusOrder = ['received', 'planning', 'executing', 'verifying', 'completed'];
                    const currentIdx = statusOrder.indexOf(activeTask.status);
                    const stepIdx = statusOrder.indexOf(step.key);
                    const isDone = currentIdx > stepIdx || activeTask.status === 'completed';
                    const isCurrent = activeTask.status === step.key;

                    return (
                      <div
                        key={step.key}
                        style={{
                          background: isCurrent ? 'rgba(6, 182, 212, 0.15)' : isDone ? 'rgba(16, 185, 129, 0.08)' : 'rgba(255,255,255,0.02)',
                          border: isCurrent ? '1px solid var(--accent-cyan)' : isDone ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-md)',
                          padding: '0.75rem',
                          textAlign: 'center',
                          position: 'relative',
                        }}
                      >
                        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: isCurrent ? 'var(--accent-cyan)' : isDone ? '#34d399' : 'var(--text-dim)' }}>
                          {step.label}
                        </div>
                        <div style={{ fontSize: '0.6875rem', color: 'var(--text-dim)', marginTop: '0.125rem' }}>
                          {step.desc}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Real-time Event Stream Log */}
                <div style={{ background: '#05070c', borderRadius: 'var(--radius-md)', padding: '0.875rem', border: '1px solid rgba(255,255,255,0.05)', maxHeight: '160px', overflowY: 'auto', fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                  <div style={{ color: 'var(--text-dim)', marginBottom: '0.375rem', display: 'flex', justifyContent: 'space-between' }}>
                    <span>LIVE EVENT LOG (SSE Stream with Reconnect)</span>
                    <span>{liveEvents.length} events</span>
                  </div>
                  {liveEvents.length === 0 ? (
                    <div style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>Listening for live pipeline events...</div>
                  ) : (
                    liveEvents.map((ev, i) => (
                      <div key={i} style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.25rem' }}>
                        <span style={{ color: 'var(--text-dim)' }}>[{ev.time}]</span>
                        <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{ev.event}:</span>
                        <span style={{ color: '#cbd5e1' }}>{JSON.stringify(ev.payload)}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Jev Orchestration & Obsidian Engineering Memory Badges */}
              {(activeTask.orchestration_decision || activeTask.memory_sync_status) && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  {/* Jev Decision Card */}
                  {activeTask.orchestration_decision && (
                    <div className="glass-panel" style={{ padding: '1.25rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                        <Cpu size={16} color="var(--accent-violet)" />
                        <h3 style={{ fontSize: '0.9375rem', fontWeight: 700 }}>Jev System One Orchestration</h3>
                      </div>
                      <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
                        <div>Provider: <strong>{activeTask.orchestration_decision.provider}</strong></div>
                        {activeTask.orchestration_decision.answers?.investigation_scope && (
                          <div>Scope: <span style={{ color: 'var(--accent-cyan)' }}>{activeTask.orchestration_decision.answers.investigation_scope.decision}</span></div>
                        )}
                        {activeTask.orchestration_decision.answers?.complexity_score && (
                          <div>Complexity: <span style={{ color: 'var(--accent-violet)' }}>{activeTask.orchestration_decision.answers.complexity_score.level}</span></div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Obsidian Memory Card */}
                  {activeTask.memory_sync_status && (
                    <div className="glass-panel" style={{ padding: '1.25rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                        <BookOpen size={16} color="#ec4899" />
                        <h3 style={{ fontSize: '0.9375rem', fontWeight: 700 }}>Obsidian Engineering Memory</h3>
                      </div>
                      <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
                        <div>Status: <span style={{ color: activeTask.memory_sync_status.synced_to_vault ? '#34d399' : '#fbbf24' }}>{activeTask.memory_sync_status.status}</span></div>
                        <div>Vault Path: <code style={{ fontFamily: 'var(--font-mono)' }}>{activeTask.memory_sync_status.vault_path}</code></div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Investigation Report Card */}
              {reportError && (
                <div className="glass-panel" style={{ padding: '1.25rem', color: '#f87171', border: '1px solid rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.08)' }}>
                  <AlertTriangle size={16} style={{ verticalAlign: 'middle', marginRight: '0.5rem' }} />
                  {reportError}
                </div>
              )}

              {reportLoading ? (
                <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                  <RefreshCw size={24} className="pulse-indicator" style={{ marginBottom: '1rem' }} />
                  <div>Synthesizing structured investigation report with OpenAI...</div>
                </div>
              ) : report ? (
                <div className="glass-panel" style={{ padding: '1.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '1rem', marginBottom: '1.5rem' }}>
                    <div>
                      <h2 style={{ fontSize: '1.25rem', fontWeight: 800 }}>Investigation Findings & Report</h2>
                      <p style={{ fontSize: '0.8125rem', color: 'var(--text-dim)' }}>
                        Evidence-bounded engineering diagnosis based on {report.evidence_stats.files_retrieved} inspected source files
                      </p>
                    </div>
                    <span className="badge badge-completed">
                      Verified Report
                    </span>
                  </div>

                  {/* Executive Summary */}
                  <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', marginBottom: '1.75rem' }}>
                    <h3 style={{ fontSize: '0.875rem', textTransform: 'uppercase', color: 'var(--text-dim)', letterSpacing: '0.05em', marginBottom: '0.5rem' }}>
                      Executive Summary
                    </h3>
                    <p style={{ fontSize: '0.9375rem', lineHeight: 1.6, color: '#f1f5f9' }}>
                      {report.summary}
                    </p>
                  </div>

                  {/* Findings */}
                  <div style={{ marginBottom: '1.75rem' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <FileCode size={18} color="var(--accent-cyan)" />
                      Key Findings ({report.findings.length})
                    </h3>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                      {report.findings.length === 0 ? (
                        <div style={{ fontStyle: 'italic', color: 'var(--text-dim)' }}>No specific defects or vulnerabilities found in inspected files.</div>
                      ) : (
                        report.findings.map((f, idx) => (
                          <div
                            key={idx}
                            style={{
                              background: 'rgba(15, 23, 42, 0.4)',
                              border: '1px solid var(--border-subtle)',
                              borderRadius: 'var(--radius-md)',
                              padding: '1.25rem',
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                              <h4 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-main)' }}>
                                {idx + 1}. {f.title}
                              </h4>
                              <span style={{ fontSize: '0.6875rem', fontWeight: 700, textTransform: 'uppercase', padding: '0.2rem 0.5rem', borderRadius: 'var(--radius-full)', background: f.confidence === 'high' ? 'rgba(16, 185, 129, 0.15)' : f.confidence === 'medium' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(100, 116, 139, 0.15)', color: f.confidence === 'high' ? '#34d399' : f.confidence === 'medium' ? '#fbbf24' : '#94a3b8' }}>
                                {f.confidence} Confidence
                              </span>
                            </div>

                            <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: '0.875rem' }}>
                              {f.explanation}
                            </p>

                            {f.evidence_paths && f.evidence_paths.length > 0 && (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem', alignItems: 'center' }}>
                                <span style={{ fontSize: '0.6875rem', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Evidence:</span>
                                {f.evidence_paths.map((p, pi) => (
                                  <span key={pi} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', background: 'rgba(255,255,255,0.04)', padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-subtle)', color: 'var(--accent-cyan)' }}>
                                    {p}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* Root Cause & Recommendations Grid */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem', marginBottom: '1.75rem' }}>
                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                      <h4 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--accent-violet)', marginBottom: '0.75rem' }}>
                        Root Cause Hypotheses
                      </h4>
                      <ul style={{ paddingLeft: '1.25rem', fontSize: '0.8125rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {report.root_cause_hypotheses.map((h, i) => (
                          <li key={i}>{h}</li>
                        ))}
                      </ul>
                    </div>

                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                      <h4 style={{ fontSize: '0.875rem', fontWeight: 700, color: '#34d399', marginBottom: '0.75rem' }}>
                        Recommended Next Steps
                      </h4>
                      <ul style={{ paddingLeft: '1.25rem', fontSize: '0.8125rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {report.recommended_next_steps.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  {/* Limitations */}
                  {report.limitations && report.limitations.length > 0 && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', borderTop: '1px solid var(--border-subtle)', paddingTop: '1rem' }}>
                      <strong>Investigation Limitations & Grounding:</strong>
                      <ul style={{ paddingLeft: '1.25rem', marginTop: '0.25rem' }}>
                        {report.limitations.map((l, i) => (
                          <li key={i}>{l}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ) : null}
            </>
          ) : (
            <div className="glass-panel" style={{ padding: '4rem 2rem', textAlign: 'center' }}>
              <Shield size={48} color="var(--accent-cyan)" style={{ opacity: 0.4, margin: '0 auto 1.5rem' }} />
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '0.5rem' }}>No Active Investigation Selected</h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', maxWidth: '420px', margin: '0 auto 1.5rem' }}>
                Select a previous investigation from the queue on the left or submit a new target GitHub repository.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Auth Modal */}
      {showAuthModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div className="glass-panel" style={{ width: '400px', padding: '2rem', position: 'relative' }}>
            <button
              onClick={() => setShowAuthModal(false)}
              style={{ position: 'absolute', top: '1rem', right: '1rem', background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: '1.25rem' }}
            >
              ✕
            </button>

            <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '0.5rem' }}>
              {authMode === 'login' ? 'Sign in to Hawk' : 'Register Account'}
            </h2>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-dim)', marginBottom: '1.5rem' }}>
              Managed Identity Provider & PostgreSQL User Authentication
            </p>

            <form onSubmit={handleAuth}>
              {authMode === 'register' && (
                <div className="input-group">
                  <label className="input-label">Full Name</label>
                  <input
                    type="text"
                    className="input-field"
                    value={authName}
                    onChange={(e) => setAuthName(e.target.value)}
                    required
                  />
                </div>
              )}

              <div className="input-group">
                <label className="input-label">Email Address</label>
                <input
                  type="email"
                  className="input-field"
                  value={authEmail}
                  onChange={(e) => setAuthEmail(e.target.value)}
                  placeholder="engineer@corp.com"
                  required
                />
              </div>

              <div className="input-group">
                <label className="input-label">Password</label>
                <input
                  type="password"
                  className="input-field"
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                  required
                />
              </div>

              {authError && (
                <div style={{ background: 'rgba(239, 68, 68, 0.1)', color: '#f87171', padding: '0.5rem', borderRadius: '4px', fontSize: '0.75rem', marginBottom: '1rem' }}>
                  {authError}
                </div>
              )}

              <button type="submit" className="btn btn-primary" style={{ width: '100%', marginBottom: '1rem' }}>
                {authMode === 'login' ? 'Sign In' : 'Create Account'}
              </button>

              <div style={{ textAlign: 'center', fontSize: '0.8125rem', color: 'var(--text-dim)' }}>
                {authMode === 'login' ? (
                  <span>Need an account? <a href="#register" onClick={() => setAuthMode('register')} style={{ color: 'var(--accent-cyan)' }}>Register</a></span>
                ) : (
                  <span>Already have an account? <a href="#login" onClick={() => setAuthMode('login')} style={{ color: 'var(--accent-cyan)' }}>Sign In</a></span>
                )}
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
