import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  deleteAllConversations,
  deleteConversation,
  getConversation,
  listConversations,
  streamChat,
  type Conversation,
} from '../lib/api'
import { MessageView, type ChatMessage } from './MessageView'

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
      })),
    )
  }

  function newConversation() {
    // 답변을 받는 중이면 그 스트림을 끊는다. 끊지 않으면 뒤늦게 온 done이 이전 대화로 되돌린다.
    // 서버는 끊겨도 답변을 저장하므로 대화 목록에서 다시 열 수 있다.
    abortRef.current?.abort()
    setSidebarOpen(false)
    setConversationId(null)
    setMessages([])
  }

  async function removeConversation(c: Conversation) {
    if (busy || !window.confirm(`'${c.title}' 대화를 삭제할까요? 되돌릴 수 없습니다.`)) return
    try {
      await deleteConversation(c.id)
      if (c.id === conversationId) newConversation()
      refreshConversations()
    } catch (e) {
      if ((e as { status?: number })?.status === 401) onAuthError()
      else window.alert(e instanceof Error ? e.message : '삭제에 실패했습니다')
    }
  }

  async function removeAll() {
    if (busy || !window.confirm('모든 대화를 삭제할까요? 되돌릴 수 없습니다.')) return
    try {
      await deleteAllConversations()
      newConversation()
      refreshConversations()
    } catch (e) {
      if ((e as { status?: number })?.status === 401) onAuthError()
      else window.alert(e instanceof Error ? e.message : '삭제에 실패했습니다')
    }
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
      {
        key: aKey,
        role: 'assistant',
        content: '',
        streaming: true,
        status: '질문을 보내는 중',
        startedAt: Date.now(),
      },
    ])
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await streamChat(
        { message: question, conversation_id: conversationId },
        {
          onStatus: (status) => patch(aKey, (m) => ({ ...m, status })),
          onToken: (t) => patch(aKey, (m) => ({ ...m, content: m.content + t })),
          onSources: (sources) => patch(aKey, (m) => ({ ...m, sources })),
          onDone: (d) => {
            if (ctrl.signal.aborted) return // 이미 다른 대화로 넘어갔다
            setConversationId(d.conversation_id)
            patch(aKey, (m) => ({ ...m, streaming: false, messageId: d.message_id }))
          },
        },
        ctrl.signal,
      )
      refreshConversations()
    } catch (e) {
      if (ctrl.signal.aborted) return refreshConversations() // 사용자가 새 대화로 넘어갔다
      const status = (e as { status?: number })?.status
      if (status === 401) return onAuthError()
      patch(aKey, (m) => ({
        ...m,
        streaming: false,
        error: e instanceof Error ? e.message : '요청 실패',
      }))
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null
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
            <div key={c.id} className={`conv-row ${c.id === conversationId ? 'active' : ''}`}>
              <button
                type="button"
                className="conv"
                onClick={() => void openConversation(c.id)}
                title={c.title}
              >
                {c.title}
              </button>
              <button
                type="button"
                className="conv-delete"
                onClick={() => void removeConversation(c)}
                aria-label={`'${c.title}' 대화 삭제`}
                title="대화 삭제"
              >
                ✕
              </button>
            </div>
          ))}
          {!conversations.length && <p className="muted small">아직 대화가 없습니다.</p>}
        </nav>
        {conversations.length > 0 && (
          <button
            type="button"
            className="ghost danger delete-all"
            onClick={() => void removeAll()}
          >
            대화 전체 삭제
          </button>
        )}
      </aside>
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <section className="chat">
        <div className="chat-toolbar only-mobile">
          <button
            type="button"
            className="ghost"
            onClick={() => setSidebarOpen(true)}
            aria-label="대화 목록 열기"
          >
            ☰ 대화 목록
          </button>
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

        <form className={`composer ${busy ? 'busy' : ''}`} onSubmit={submit}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                void ask(input)
              }
            }}
            placeholder={busy ? '답변을 기다리는 중이에요…' : '질문을 입력하세요'}
            disabled={busy}
            rows={1}
            maxLength={2000}
            aria-label="질문"
          />
          <button type="submit" className="send" disabled={busy || !input.trim()}>
            {busy ? (
              <>
                <span className="spinner light" aria-hidden /> 답변 중
              </>
            ) : (
              '보내기'
            )}
          </button>
        </form>
      </section>
    </div>
  )
}
