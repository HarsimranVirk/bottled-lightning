const API = '/api';

async function json(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try { const body = await res.json(); detail = body.detail || JSON.stringify(body); } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  listViews: () => json(fetch(`${API}/views`).then(r => r)),
  addView: (body) => json(fetch(`${API}/views`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })),
  deleteView: (id) => json(fetch(`${API}/views/${id}`, { method: 'DELETE' })),
  runView: (id) => json(fetch(`${API}/views/${id}/run`, { method: 'POST' })),
  listJobs: () => json(fetch(`${API}/jobs`).then(r => r)),
  job: (id) => json(fetch(`${API}/jobs/${id}`).then(r => r)),
  results: (viewId) => json(fetch(`${API}/views/${viewId}/results`).then(r => r)),
  sessionStatus: () => json(fetch(`${API}/session`).then(r => r)),
};
