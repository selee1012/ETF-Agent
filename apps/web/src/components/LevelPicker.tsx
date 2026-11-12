// 설명 수준 선택: 처음 로그인할 때(온보딩)와 프로필 수정에서 쓴다. # P1-API-01
import { useEffect, useState } from 'react'
import { updateProfile, type Level, type User } from '../lib/api'
import { LEVELS } from '../lib/levels'

function LevelOptions({ value, onChange }: { value: Level | null; onChange: (l: Level) => void }) {
  return (
    <div className="level-options" role="radiogroup" aria-label="설명 수준">
      {LEVELS.map((l) => (
        <button
          type="button"
          key={l.value}
          role="radio"
          aria-checked={value === l.value}
          className={`level-card ${value === l.value ? 'on' : ''}`}
          onClick={() => onChange(l.value)}
        >
          <span className="level-name">{l.label}</span>
          <span className="level-who">{l.who}</span>
          <span className="level-how muted">{l.how}</span>
        </button>
      ))}
    </div>
  )
}

function useSave(onSaved: (u: User) => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function save(level: Level) {
    setBusy(true)
    setError(null)
    try {
      onSaved(await updateProfile({ level }))
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장에 실패했습니다')
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, save }
}

/** 처음 로그인한 사용자(level 미설정)에게 보여 주는 화면. */
export function LevelOnboarding({ user, onDone }: { user: User; onDone: (u: User) => void }) {
  const [level, setLevel] = useState<Level | null>(null)
  const { busy, error, save } = useSave(onDone)
  return (
    <main className="login">
      <div className="card onboarding">
        <h1>반가워요!</h1>
        <p className="muted">
          {user.email} 님에게 맞는 설명 수준을 골라 주세요. 모든 답변이 이 수준에 맞춰 나오고,
          나중에 상단의 프로필에서 언제든 바꿀 수 있어요.
        </p>
        <LevelOptions value={level} onChange={setLevel} />
        <button type="button" disabled={!level || busy} onClick={() => level && void save(level)}>
          {busy ? '저장 중…' : '시작하기'}
        </button>
        {error && <p className="error">{error}</p>}
      </div>
    </main>
  )
}

/** 상단바 프로필 버튼으로 여는 수정 창. */
export function ProfileDialog({
  user,
  onClose,
  onSaved,
}: {
  user: User
  onClose: () => void
  onSaved: (u: User) => void
}) {
  const [level, setLevel] = useState<Level | null>(user.level)
  const { busy, error, save } = useSave((u) => {
    onSaved(u)
    onClose()
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div
        className="card modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="profile-title">프로필</h2>
        <p className="muted small">{user.email}</p>
        <h3 className="small">설명 수준</h3>
        <LevelOptions value={level} onChange={setLevel} />
        <p className="hint">바꾼 수준은 다음 질문부터 적용돼요.</p>
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            disabled={!level || level === user.level || busy}
            onClick={() => level && void save(level)}
          >
            {busy ? '저장 중…' : '저장'}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
