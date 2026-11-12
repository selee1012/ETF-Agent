import { useEffect, useState } from 'react'
import { sendFeedback, type FeedbackKind, type Source } from '../lib/api'
import { Markdown } from './Markdown'

export type ChatMessage = {
  key: string
  role: 'user' | 'assistant'
  content: string
  status?: string | null
  sources?: Source[]
  messageId?: string | null
  streaming?: boolean
  startedAt?: number
  error?: string | null
}

const DISCLAIMER_HEADER = '---\n**고지**'

// 예전에 저장된 답변에 남아 있는 근거 번호([1], [1, 2])와 '설명 수준' 줄을 화면에서 지운다
const CITATION = /[ \t]*\[\d{1,2}(?:\s*,\s*\d{1,2})*\]/g
const LEVEL_LINE = /^\s*_설명 수준:[^\n]*_\s*$/gm

function cleanAnswer(text: string): string {
  return text.replace(LEVEL_LINE, '').replace(CITATION, '').trim()
}

/** 답변을 기다리는 동안 지난 시간(초). */
function useElapsed(startedAt: number | undefined, running: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [running])
  return startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0
}

function Waiting({ status, seconds }: { status?: string | null; seconds: number }) {
  return (
    <div className="waiting" role="status" aria-live="polite">
      <span className="typing" aria-hidden>
        <i />
        <i />
        <i />
      </span>
      <span>
        <strong>답변을 준비하고 있어요</strong>
        <span className="muted small">
          {status ?? '처리 중'}
          {seconds > 0 && ` · ${seconds}초`}
          {seconds >= 15 && ' · 자세한 설명은 조금 더 걸려요'}
        </span>
      </span>
    </div>
  )
}

function splitDisclaimer(content: string): [string, string | null] {
  const idx = content.indexOf(DISCLAIMER_HEADER)
  if (idx < 0) return [content, null]
  return [content.slice(0, idx).trim(), content.slice(idx + DISCLAIMER_HEADER.length).trim()]
}

function SourceList({ sources }: { sources: Source[] }) {
  if (!sources.length) return null
  return (
    <div className="sources">
      <span className="label">출처</span>
      <ol>
        {sources.map((s, i) => (
          <li key={i}>
            {s.url ? (
              <a href={s.url} target="_blank" rel="noreferrer noopener">
                {s.title}
              </a>
            ) : (
              <span>{s.title}</span>
            )}
            {s.location && <span className="muted"> · {s.location}</span>}
          </li>
        ))}
      </ol>
    </div>
  )
}

function Feedback({ messageId }: { messageId: string }) {
  const [sent, setSent] = useState<FeedbackKind | null>(null)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function send(kind: FeedbackKind, correction?: string) {
    setError(null)
    try {
      await sendFeedback({ kind, message_id: messageId, correction_text: correction })
      setSent(kind)
      setEditing(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  if (sent) return <div className="feedback muted">피드백이 저장되었습니다. 감사합니다.</div>
  return (
    <div className="feedback">
      <button type="button" className="ghost" onClick={() => send('like')} aria-label="좋아요">
        👍
      </button>
      <button type="button" className="ghost" onClick={() => send('dislike')} aria-label="싫어요">
        👎
      </button>
      <button type="button" className="ghost" onClick={() => setEditing((v) => !v)}>
        정정 제안
      </button>
      {editing && (
        <form
          className="correction"
          onSubmit={(e) => {
            e.preventDefault()
            if (text.trim()) void send('correction', text.trim())
          }}
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="어떤 부분이 틀렸는지 알려 주세요"
            rows={2}
          />
          <button type="submit" disabled={!text.trim()}>
            보내기
          </button>
        </form>
      )}
      {error && <span className="error">{error}</span>}
    </div>
  )
}

export function MessageView({ m }: { m: ChatMessage }) {
  const waiting = m.role === 'assistant' && !!m.streaming && !m.content
  const seconds = useElapsed(m.startedAt, waiting)
  if (m.role === 'user') {
    return (
      <div className="msg user">
        <div className="bubble">{m.content}</div>
      </div>
    )
  }
  const [raw, disclaimer] = splitDisclaimer(m.content)
  const body = cleanAnswer(raw)
  return (
    <div className="msg assistant">
      <div className="bubble">
        {waiting && <Waiting status={m.status} seconds={seconds} />}
        {body && <Markdown text={body} />}
        {m.streaming && m.content && <span className="cursor" aria-hidden />}
        {m.error && <p className="error">{m.error}</p>}
        {disclaimer && (
          <aside className="disclaimer">
            <Markdown text={disclaimer} />
          </aside>
        )}
        {!m.streaming && <SourceList sources={m.sources ?? []} />}
        {!m.streaming && m.messageId && <Feedback messageId={m.messageId} />}
      </div>
    </div>
  )
}
