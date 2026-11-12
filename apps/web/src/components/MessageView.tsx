import { useState } from 'react'
import { sendFeedback, type FeedbackKind, type Source } from '../lib/api'
import { Markdown } from './Markdown'

export type ChatMessage = {
  key: string
  role: 'user' | 'assistant'
  content: string
  status?: string | null
  sources?: Source[]
  messageId?: string | null
  verdict?: string | null
  intents?: string[]
  streaming?: boolean
  error?: string | null
}

const DISCLAIMER_HEADER = '---\n**고지**'

const VERDICT_LABEL: Record<string, string> = {
  pass: '점검 통과',
  pass_after_retry: '재작성 후 통과',
  blocked: '안전 답변으로 대체',
  template: '고정 안내',
  llm_unavailable: '모델 응답 불가',
  error: '오류',
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
            placeholder="어떤 부분이 틀렸는지 알려 주세요 (개인정보는 자동으로 가려집니다)"
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
  if (m.role === 'user') {
    return (
      <div className="msg user">
        <div className="bubble">{m.content}</div>
      </div>
    )
  }
  const [body, disclaimer] = splitDisclaimer(m.content)
  return (
    <div className="msg assistant">
      <div className="bubble">
        {m.streaming && m.status && !m.content && (
          <div className="status">
            <span className="spinner" aria-hidden /> {m.status}
          </div>
        )}
        {body && <Markdown text={body} />}
        {m.streaming && m.content && <span className="cursor" aria-hidden />}
        {m.error && <p className="error">{m.error}</p>}
        {disclaimer && (
          <aside className="disclaimer">
            <Markdown text={disclaimer} />
          </aside>
        )}
        {!m.streaming && <SourceList sources={m.sources ?? []} />}
        {!m.streaming && m.verdict && (
          <div className="meta muted">
            {m.intents?.length ? `의도: ${m.intents.join(', ')} · ` : ''}
            가드: {VERDICT_LABEL[m.verdict] ?? m.verdict}
          </div>
        )}
        {!m.streaming && m.messageId && <Feedback messageId={m.messageId} />}
      </div>
    </div>
  )
}
