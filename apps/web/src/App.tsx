import { useCallback, useEffect, useState } from 'react'
import { AdminView } from './components/AdminView'
import { ChatView } from './components/ChatView'
import { LevelOnboarding, ProfileDialog } from './components/LevelPicker'
import { Login } from './components/Login'
import { clearSession, getMe, getStoredUser, getToken, type User } from './lib/api'
import { levelLabel } from './lib/levels'

type View = 'chat' | 'admin'

function App() {
  const [user, setUser] = useState<User | null>(() => (getToken() ? getStoredUser() : null))
  // 저장된 사용자 정보는 예전 것일 수 있어 서버 프로필로 한 번 확인한다(설명 수준 포함)
  const [checked, setChecked] = useState(false)
  const [view, setView] = useState<View>('chat')
  const [profileOpen, setProfileOpen] = useState(false)

  const logout = useCallback(() => {
    clearSession()
    setUser(null)
    setView('chat')
    setProfileOpen(false)
  }, [])

  useEffect(() => {
    if (!getToken()) return
    getMe()
      .then(setUser)
      .catch((e) => {
        if (e?.status === 401 || e?.status === 404) logout()
      })
      .finally(() => setChecked(true))
  }, [logout])

  const onLogin = (u: User) => {
    setUser(u)
    setChecked(true)
  }

  if (!user) return <Login onLogin={onLogin} />
  if (!user.level) {
    if (!checked) return <main className="login muted">불러오는 중…</main>
    return <LevelOnboarding user={user} onDone={setUser} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <strong className="brand">ETF Agent</strong>
        <span className="sample-tag">샘플 데이터</span>
        <nav>
          <button
            type="button"
            className={view === 'chat' ? 'tab on' : 'tab'}
            onClick={() => setView('chat')}
          >
            채팅
          </button>
          {user.role === 'admin' && (
            <button
              type="button"
              className={view === 'admin' ? 'tab on' : 'tab'}
              onClick={() => setView('admin')}
            >
              운영
            </button>
          )}
        </nav>
        <span className="spacer" />
        <button
          type="button"
          className="ghost profile-button"
          onClick={() => setProfileOpen(true)}
          title="프로필 수정"
        >
          <span className="user-email">{user.email}</span>
          <span className="level-badge">{levelLabel(user.level)}</span>
        </button>
        <button type="button" className="ghost" onClick={logout}>
          로그아웃
        </button>
      </header>
      {view === 'admin' && user.role === 'admin' ? (
        <AdminView />
      ) : (
        <ChatView onAuthError={logout} />
      )}
      {profileOpen && (
        <ProfileDialog user={user} onClose={() => setProfileOpen(false)} onSaved={setUser} />
      )}
    </div>
  )
}

export default App
