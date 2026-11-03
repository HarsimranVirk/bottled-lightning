const API = '/api';

async function json(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.clone().json();
      detail = body.detail || JSON.stringify(body);
    } catch { /* non-JSON error body */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

const get = (path) => fetch(`${API}${path}`).then(json);
const post = (path, body) => fetch(`${API}${path}`, {
  method: 'POST',
  headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
  body: body !== undefined ? JSON.stringify(body) : undefined,
}).then(json);
const del = (path) => fetch(`${API}${path}`, { method: 'DELETE' }).then(json);

export const api = {
  listViews: () => get('/views'),
  addView: (body) => post('/views', body),
  deleteView: (id) => del(`/views/${id}`),
  runView: (id) => post(`/views/${id}/run`),
  listJobs: () => get('/jobs'),
  job: (id) => get(`/jobs/${id}`),
  results: (viewId) => get(`/views/${viewId}/results`),
  sessionStatus: () => get('/session'),
  startLogin: (reset = false) => post('/session/login', { reset }),
  resetSession: () => post('/session/reset'),
  deviations: () => get('/deviations'),
  runDeviations: () => post('/deviations/run'),
  decide: (value, decision) => post(`/deviations/${encodeURIComponent(value)}/decision`, { decision }),
  devResync: () => post('/deviations/resync'),
  devResyncStatus: () => get('/deviations/resync'),
};
