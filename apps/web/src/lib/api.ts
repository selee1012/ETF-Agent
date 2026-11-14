// FastAPI 클라이언트. 주소는 VITE_API_BASE_URL, 토큰은 localStorage에 둔다(개발용 local 인증).
// .env.example을 복사만 하면 빈 값이 들어오므로 ??가 아니라 ||로 기본 주소를 쓴다.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(
  /\/$/,
  '',
)

const TOKEN_KEY = 'etf-agent.token'
const USER_KEY = 'etf-agent.user'

export type Level = 'beginner' | 'intermediate' | 'expert'
// level이 null이면 아직 설명 수준을 고르지 않은 사용자(온보딩 화면을 띄운다)
export type User = {
  id: string
  email: string
  role: 'user' | 'admin' | string
  level: Level | null
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY)
  return raw ? (JSON.parse(raw) as User) : null
}

export function saveSession(token: string, user: User) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const resp = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = await resp.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* 본문 없음 */
    }
    if (resp.status === 401) clearSession()
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

// ---------- 인증 ----------
export async function devLogin(email: string): Promise<User> {
  const res = await request<{ access_token: string; user: User }>('/auth/dev-login', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
  saveSession(res.access_token, res.user)
  return res.user
}

function storeUser(user: User): User {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  return user
}

/** 서버의 최신 프로필(설명 수준 포함)로 저장된 사용자 정보를 갱신한다. */
export const getMe = () => request<User>('/auth/me').then(storeUser)

export const updateProfile = (body: { level: Level }) =>
  request<User>('/auth/me', { method: 'PATCH', body: JSON.stringify(body) }).then(storeUser)

// ---------- 채팅 ----------
export type Source = {
  title: string
  location: string | null
  url: string | null
  kind: 'document' | 'disclosure' | 'etf_data' | string
}
export type DoneEvent = {
  request_id: string
  conversation_id: string
  message_id: string | null
  intents: string[]
  guard: { verdict: string; reasons: string[] }
  latency_ms: number
}
export type ChatHandlers = {
  onStatus: (message: string, stage: string) => void
  onToken: (text: string) => void
  onSources: (sources: Source[]) => void
  onDone: (done: DoneEvent) => void
  /** 서버가 대화를 만들거나 찾은 직후 알려 주는 대화 id(done 전에 온다) */
  onConversation?: (conversationId: string) => void
}

/** POST /chat SSE를 fetch 스트림으로 읽는다(EventSource는 POST를 지원하지 않는다).
 * 설명 수준은 보내지 않는다: 서버가 사용자 프로필의 수준으로 답한다.
 * 서버가 error 이벤트를 보내거나 done 없이 스트림이 끝나면 예외를 던진다(화면이 '답변 중'에 멈추지 않게). */
export async function streamChat(
  body: { message: string; conversation_id?: string | null },
  handlers: ChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken()
  const resp = await fetch(`${API_BASE_URL}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    if (resp.status === 401) clearSession()
    throw new ApiError(resp.status, `채팅 요청 실패 (${resp.status})`)
  }
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let finished = false
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      if (dispatch(block, handlers)) finished = true
    }
  }
  if (!finished) throw new ApiError(0, '답변이 중간에 끊겼습니다. 다시 시도해 주세요.')
}

/** 이벤트 하나를 처리한다. done이면 true. */
function dispatch(block: string, h: ChatHandlers): boolean {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7)
    else if (line.startsWith('data: ')) data.push(line.slice(6))
  }
  if (!data.length) return false
  const payload = JSON.parse(data.join('\n'))
  if (event === 'error') throw new ApiError(500, payload.message ?? '요청을 처리하지 못했습니다')
  if (event === 'status') {
    if (payload.conversation_id) h.onConversation?.(payload.conversation_id)
    h.onStatus(payload.message, payload.stage)
  } else if (event === 'token') h.onToken(payload.text)
  else if (event === 'sources') h.onSources(payload.sources)
  else if (event === 'done') h.onDone(payload)
  return event === 'done'
}

// ---------- 이력·피드백 ----------
export type Conversation = { id: string; title: string; created_at: string; updated_at: string }
export type StoredMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  request_id: string | null
  intent: string | null
  guard_verdict: string | null
  sources: Source[]
  created_at: string
}

export const listConversations = () => request<Conversation[]>('/history')
export const getConversation = (id: string) =>
  request<Conversation & { messages: StoredMessage[] }>(`/history/${id}`)
export const deleteConversation = (id: string) =>
  request<void>(`/history/${id}`, { method: 'DELETE' })
export const deleteAllConversations = () =>
  request<{ deleted: number }>('/history', { method: 'DELETE' })

export type FeedbackKind = 'like' | 'dislike' | 'correction'
export const sendFeedback = (body: {
  kind: FeedbackKind
  message_id: string
  correction_text?: string
}) => request<{ id: number }>('/feedback', { method: 'POST', body: JSON.stringify(body) })

// ---------- 운영 화면 ----------
export type Trace = {
  request_id: string
  user_id: string | null
  intent: string | null
  agents: string[]
  retrieved_doc_ids: string[]
  guard_verdict: string | null
  guard_reasons: string[]
  latency_ms: number | null
  model: string | null
  fallback_used: boolean
  created_at: string
}
export type FeedbackRow = {
  id: number
  message_id: string | null
  request_id: string | null
  user_id: string | null
  kind: string
  correction_text: string | null
  created_at: string
}
export type DocumentRow = {
  id: number
  title: string
  source_uri: string
  doc_type: string
  embedding_model: string
  chunks: number
  updated_at: string
}
export type SearchHit = {
  chunk_id: number
  title: string
  location: string
  score: number
  vector_score: number
  text_score: number
  preview: string
}

export const adminTraces = (q: { intent?: string; verdict?: string; offset?: number }) => {
  const p = new URLSearchParams({ limit: '50', offset: String(q.offset ?? 0) })
  if (q.intent) p.set('intent', q.intent)
  if (q.verdict) p.set('verdict', q.verdict)
  return request<{ items: Trace[]; total: number }>(`/admin/traces?${p}`)
}
export const adminFeedback = () => request<FeedbackRow[]>('/admin/feedback')
export const adminDocuments = () => request<DocumentRow[]>('/admin/documents')
export const adminSearch = (q: string) =>
  request<SearchHit[]>(`/admin/search?q=${encodeURIComponent(q)}`)
export const adminUpload = (file: File, docType: string) => {
  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)
  return request<{ document_id: number; title: string; status: string; chunks: number }>(
    '/admin/documents',
    { method: 'POST', body: form },
  )
}
