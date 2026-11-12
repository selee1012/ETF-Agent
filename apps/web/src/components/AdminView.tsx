// 운영 화면(P1-FE-03): 트레이스(마스킹 정보만)·피드백 조회, 문서 업로드 → ingest → 검색 확인
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  adminDocuments,
  adminFeedback,
  adminSearch,
  adminTraces,
  adminUpload,
  type DocumentRow,
  type FeedbackRow,
  type SearchHit,
  type Trace,
} from '../lib/api'

const INTENTS = ['', 'etf_info', 'faq', 'disclosure', 'high_risk', 'recommendation', 'out_of_scope', 'blocked']
const VERDICTS = ['', 'pass', 'pass_after_retry', 'blocked', 'template', 'llm_unavailable', 'error']
type Tab = 'traces' | 'feedback' | 'documents'

const fmtTime = (iso: string) => new Date(iso).toLocaleString('ko-KR', { hour12: false })

function Traces() {
  const [intent, setIntent] = useState('')
  const [verdict, setVerdict] = useState('')
  const [data, setData] = useState<{ items: Trace[]; total: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    adminTraces({ intent, verdict })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }, [intent, verdict])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section>
      <div className="filters">
        <label>
          의도
          <select value={intent} onChange={(e) => setIntent(e.target.value)}>
            {INTENTS.map((i) => (
              <option key={i} value={i}>
                {i || '전체'}
              </option>
            ))}
          </select>
        </label>
        <label>
          가드 판정
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {v || '전체'}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="ghost" onClick={load}>
          새로고침
        </button>
        {data && <span className="muted">총 {data.total}건</span>}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>시각</th>
              <th>의도</th>
              <th>에이전트</th>
              <th>가드</th>
              <th>사유</th>
              <th>검색 문서</th>
              <th>지연(ms)</th>
              <th>모델</th>
              <th>request_id</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((t) => (
              <tr key={t.request_id}>
                <td>{fmtTime(t.created_at)}</td>
                <td>{t.intent}</td>
                <td>{t.agents.join(', ')}</td>
                <td>
                  <span className={`badge ${t.guard_verdict}`}>{t.guard_verdict}</span>
                </td>
                <td className="small">{t.guard_reasons.join(', ')}</td>
                <td className="small">{t.retrieved_doc_ids.join(', ')}</td>
                <td>{t.latency_ms}</td>
                <td className="small">
                  {t.model}
                  {t.fallback_used ? ' (fallback)' : ''}
                </td>
                <td className="small mono">{t.request_id.slice(0, 12)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">트레이스에는 질의 원문이 저장되지 않습니다.</p>
    </section>
  )
}

function FeedbackList() {
  const [rows, setRows] = useState<FeedbackRow[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    adminFeedback()
      .then(setRows)
      .catch((e) => setError(e.message))
  }, [])
  return (
    <section>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>시각</th>
              <th>종류</th>
              <th>정정 내용(마스킹)</th>
              <th>request_id</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.id}>
                <td>{fmtTime(f.created_at)}</td>
                <td>
                  <span className={`badge ${f.kind}`}>{f.kind}</span>
                </td>
                <td>{f.correction_text}</td>
                <td className="small mono">{f.request_id?.slice(0, 12)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && !error && <p className="muted">피드백이 없습니다.</p>}
    </section>
  )
}

function Documents() {
  const [docs, setDocs] = useState<DocumentRow[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [docType, setDocType] = useState('faq')
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)

  const load = useCallback(() => {
    adminDocuments()
      .then(setDocs)
      .catch((e) => setError(e.message))
  }, [])
  useEffect(() => {
    load()
  }, [load])

  async function upload(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const r = await adminUpload(file, docType)
      setResult(`${r.title}: ${r.status} (청크 ${r.chunks < 0 ? '변경 없음' : r.chunks}개)`)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '업로드 실패')
    } finally {
      setBusy(false)
    }
  }

  async function search(e: FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    try {
      setHits(await adminSearch(query.trim()))
    } catch (err) {
      setError(err instanceof Error ? err.message : '검색 실패')
    }
  }

  return (
    <section className="docs">
      <form className="card upload" onSubmit={upload}>
        <h3>문서 업로드 → ingest</h3>
        <input
          type="file"
          accept=".md,.markdown,.txt,.pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <select value={docType} onChange={(e) => setDocType(e.target.value)}>
          <option value="faq">FAQ·지식</option>
          <option value="product">상품 설명</option>
          <option value="disclosure">공시 문서</option>
        </select>
        <button type="submit" disabled={!file || busy}>
          {busy ? '처리 중…' : '업로드'}
        </button>
        {result && <p className="ok">{result}</p>}
        {error && <p className="error">{error}</p>}
        <p className="muted small">같은 파일명으로 다시 올리면 내용이 갱신됩니다.</p>
      </form>

      <form className="card" onSubmit={search}>
        <h3>검색 반영 확인</h3>
        <div className="row">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="검색어(하이브리드 검색)"
          />
          <button type="submit">검색</button>
        </div>
        {hits && (
          <ol className="hits">
            {hits.map((h) => (
              <li key={h.chunk_id}>
                <strong>{h.title}</strong> · {h.location}{' '}
                <span className="muted small">
                  score {h.score} (vec {h.vector_score}, trgm {h.text_score})
                </span>
                <div className="small">{h.preview}</div>
              </li>
            ))}
          </ol>
        )}
      </form>

      <div className="table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>문서</th>
              <th>유형</th>
              <th>청크</th>
              <th>임베딩 모델</th>
              <th>위치</th>
              <th>갱신</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td>{d.title}</td>
                <td>{d.doc_type}</td>
                <td>{d.chunks}</td>
                <td className="small">{d.embedding_model}</td>
                <td className="small mono">{d.source_uri}</td>
                <td className="small">{fmtTime(d.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function AdminView() {
  const [tab, setTab] = useState<Tab>('traces')
  return (
    <div className="admin">
      <div className="tabs" role="tablist">
        {(
          [
            ['traces', '트레이스'],
            ['feedback', '피드백'],
            ['documents', '문서'],
          ] as const
        ).map(([key, label]) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab === key}
            key={key}
            className={tab === key ? 'tab on' : 'tab'}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'traces' && <Traces />}
      {tab === 'feedback' && <FeedbackList />}
      {tab === 'documents' && <Documents />}
    </div>
  )
}
