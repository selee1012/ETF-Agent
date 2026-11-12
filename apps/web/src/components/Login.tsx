import { useState, type FormEvent } from 'react'
import type { User } from '../lib/api'
import { AUTH_MODE, login } from '../lib/auth'

export function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onLogin(await login(email.trim()))
    } catch (err) {
      setError(err instanceof Error ? err.message : '로그인 실패')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login">
      <form onSubmit={submit} className="card">
        <h1>ETF Agent</h1>
        <p className="muted">ETF 질의응답 AI (개발용 로그인 · {AUTH_MODE})</p>
        <label htmlFor="email">이메일</label>
        <input
          id="email"
          type="email"
          required
          autoFocus
          placeholder="you@local.test"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <button type="submit" disabled={busy || !email}>
          {busy ? '로그인 중…' : '로그인'}
        </button>
        {error && <p className="error">{error}</p>}
        <p className="hint">
          운영 화면은 <code>admin@local.test</code>(ADMIN_EMAILS)로 로그인하세요.
        </p>
      </form>
    </main>
  )
}
