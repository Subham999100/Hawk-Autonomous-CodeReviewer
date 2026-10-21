export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface TaskSummary {
  id: string;
  objective: string;
  repository_url: string;
  status: 'received' | 'planning' | 'executing' | 'verifying' | 'completed' | 'blocked' | 'failed' | 'cancelled';
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  evidence_stats?: {
    files_discovered: number;
    files_selected: number;
    files_retrieved: number;
    total_evidence_bytes: number;
  };
  orchestration_decision?: any;
  memory_sync_status?: any;
  error_message?: string;
}

export interface Finding {
  title: string;
  explanation: string;
  evidence_paths: string[];
  confidence: 'low' | 'medium' | 'high';
}

export interface InvestigationReport {
  task_id: string;
  objective: string;
  repository: {
    full_name: string;
    description?: string;
    html_url?: string;
    default_branch?: string;
    private?: boolean;
  };
  evidence_stats: {
    files_discovered: number;
    files_selected: number;
    files_retrieved: number;
    total_evidence_bytes: number;
  };
  summary: string;
  findings: Finding[];
  root_cause_hypotheses: string[];
  recommended_next_steps: string[];
  limitations: string[];
  orchestration_decision?: any;
  memory_sync_status?: any;
}

const TOKEN_KEY = 'hawk_access_token';

export const getStoredToken = (): string | null => {
  return localStorage.getItem(TOKEN_KEY);
};

export const setStoredToken = (token: string): void => {
  localStorage.setItem(TOKEN_KEY, token);
};

export const clearStoredToken = (): void => {
  localStorage.removeItem(TOKEN_KEY);
};

const getHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const token = getStoredToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
};

export const api = {
  async register(email: string, password: string, name: string): Promise<AuthResponse> {
    const res = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Registration failed');
    }
    const data = await res.json();
    setStoredToken(data.access_token);
    return data;
  },

  async login(email: string, password: string): Promise<AuthResponse> {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Login failed');
    }
    const data = await res.json();
    setStoredToken(data.access_token);
    return data;
  },

  async getMe(): Promise<User> {
    const res = await fetch('/auth/me', {
      headers: getHeaders(),
    });
    if (!res.ok) {
      throw new Error('Not authenticated');
    }
    return res.json();
  },

  async listTasks(): Promise<TaskSummary[]> {
    const res = await fetch('/tasks', {
      headers: getHeaders(),
    });
    if (!res.ok) {
      throw new Error('Failed to fetch tasks');
    }
    return res.json();
  },

  async getTask(taskId: string): Promise<TaskSummary> {
    const res = await fetch(`/tasks/${taskId}`, {
      headers: getHeaders(),
    });
    if (!res.ok) {
      throw new Error('Failed to fetch task');
    }
    return res.json();
  },

  async getTaskReport(taskId: string): Promise<InvestigationReport> {
    const res = await fetch(`/tasks/${taskId}/report`, {
      headers: getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Report not available');
    }
    return res.json();
  },

  async submitTask(objective: string, repositoryUrl: string): Promise<{ task_id: string; status: string }> {
    const res = await fetch('/tasks', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        objective,
        repository_url: repositoryUrl,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to submit investigation task');
    }
    return res.json();
  },

  async cancelTask(taskId: string): Promise<void> {
    const res = await fetch(`/tasks/${taskId}/cancel`, {
      method: 'POST',
      headers: getHeaders(),
    });
    if (!res.ok) {
      throw new Error('Failed to cancel task');
    }
  },

  getEventSourceUrl(taskId: string): string {
    const token = getStoredToken();
    const query = token ? `?token=${encodeURIComponent(token)}` : '';
    return `/tasks/${taskId}/events${query}`;
  },
};
