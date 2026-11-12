import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  getConversation,
  listConversations,
  streamChat,
  type Conversation,
  type Level,
} from '../lib/api'
import { MessageView, type ChatMessage } from './MessageView'

const LEVELS: { value: Level; label: string }[] = [
  { value: 'beginner', label: '입문' },
  { value: 'intermediate', label: '중급' },
  { value: 'expert', label: '숙련' },
]

const EXAMPLES = [
  '샘플 코스피200이랑 샘플 미국S&P500 비교해줘',
  '샘플 미국나스닥100 괴리율 알려줘',
  'ETF 괴리율이 뭐야?',
  '샘플 반도체 최근 공시 요약해줘',
]

let seq = 0
const nextKey = () => `m${++seq}`

export function ChatView({ onAuthError }: { onAuthError: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [level, setLevel] = useState<Level>('beginner')
  const [busy, setBusy] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const refreshConversations = useCallback(() => {
    listConversations()
      .then(setConversations)
      .catch((e) => {
        if (e?.status === 401) onAuthError()
      })
  }, [onAuthError])

  useEffect(() => {
    refreshConversations()
    return () => abortRef.current?.abort()
  }, [refreshConversations])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  async function openConversation(id: string) {
    setSidebarOpen(false)
    if (busy) return
    const conv = await getConversation(id)
    setConversationId(id)
    setMessages(
      conv.messages.map((m) => ({
        key: m.id,
        role: m.role,
        content: m.content,
        sources: m.sources,
        messageId: m.role === 'assistant' ? m.id : null,
        verdict: m.guard_verdict,
        intents: m.intent ? m.intent.split('+') : [],
      })),
    )
  }

  function newConversation() {
    setSidebarOpen(false)
    setConversationId(null)
    setMessages([])
  }

  const patch = (key: string, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((ms) => ms.map((m) => (m.key === key ? fn(m) : m)))

  async function ask(text: string) {
    const question = text.trim()
    if (!question || busy) return
    setInput('')
    setBusy(true)
    const aKey = nextKey()
    setMessages((ms) => [
      ...ms,
      { key: nextKey(), role: 'user', content: question },
      { key: aKey, role: 'assistant', content: '', streaming: true, status: '요청을 보내는 중' },
    ])
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await streamChat(
        { message: question, conversation_id: conversationId, level },
        {
          onStatus: (status) => patch(aKey, (m) => ({ ...m, status })),
          onToken: (t) => patch(aKey, (m) => ({ ...m, content: m.content + t })),
          onSources: (sources) => patch(aKey, (m) => ({ ...m, sources })),
          onDone: (d) => {
            setConversationId(d.conversation_id)
            patch(aKey, (m) => ({
              ...m,
              streaming: false,
              messageId: d.message_id,
              verdict: d.guard.verdict,
              intents: d.intents,
            }))
          },
        },
        ctrl.signal,
      )
      refreshConversations()
    } catch (e) {
      const status = (e as { status?: number })?.status
      if (status === 401) return onAuthError()
      patch(aKey, (m) => ({
        ...m,
        streaming: false,
        error: e instanceof Error ? e.message : '요청 실패',
      }))
    } finally {
      setBusy(false)
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    void ask(input)
  }

  return (
    <div className="chat-layout">
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <button type="button" className="new-chat" onClick={newConversation}>
          + 새 대화
        </button>
        <nav aria-label="대화 목록">
          {conversations.map((c) => (
            <button
              type="button"
              key={c.id}
              className={`conv ${c.id === conversationId ? 'active' : ''}`}
              onClick={() => void openConversation(c.id)}
              title={c.title}
            >
              {c.title}
            </button>
          ))}
          {!conversations.length && <p className="muted small">아직 대화가 없습니다.</p>}
        </nav>
      </aside>
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <section className="chat">
        <div className="chat-toolbar">
          <button
            type="button"
            className="ghost only-mobile"
            onClick={() => setSidebarOpen(true)}
            aria-label="대화 목록 열기"
          >
            ☰
          </button>
          <div className="levels" role="radiogroup" aria-label="설명 수준">
            {LEVELS.map((l) => (
              <button
                type="button"
                key={l.value}
                role="radio"
                aria-checked={level === l.value}
                className={level === l.value ? 'chip on' : 'chip'}
                onClick={() => setLevel(l.value)}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <div className="messages">
          {!messages.length && (
            <div className="empty">
              <p>ETF 정보·개념·공시를 물어보세요. 모든 데이터는 개발용 샘플입니다.</p>
              <div className="examples">
                {EXAMPLES.map((q) => (
                  <button type="button" key={q} className="chip" onClick={() => void ask(q)}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <MessageView key={m.key} m={m} />
          ))}
          <div ref={bottomRef} />
        </div>

        <form className="composer" onSubmit={submit}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                void ask(input)
              }
            }}
            placeholder="질문을 입력하세요 (Shift+Enter 줄바꿈)"
            rows={1}
            maxLength={2000}
            aria-label="질문"
          />
          <button type="submit" disabled={busy || !input.trim()}>
            {busy ? '답변 중…' : '보내기'}
          </button>
        </form>
      </section>
    </div>
  )
}
