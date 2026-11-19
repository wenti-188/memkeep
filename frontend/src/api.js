const BASE = ''

async function req(path, method = 'GET', body) {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text.slice(0, 120)}`)
  }
  return res.json()
}

export const api = {
  chat: (message) => req('/api/v1/chat', 'POST', { message }),
  memories: (limit = 200) => req(`/api/v1/memories?limit=${limit}`),
  remove: (id) => req(`/api/v1/memories/${id}`, 'DELETE'),
  conflicts: (limit = 30) => req(`/api/v1/conflicts?limit=${limit}`),
  health: () => req('/health'),
  metrics: () => req('/metrics'),
}
