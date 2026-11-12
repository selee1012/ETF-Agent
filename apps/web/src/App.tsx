import { useCallback, useState } from 'react'
import { AdminView } from './components/AdminView'
import { ChatView } from './components/ChatView'
import { Login } from './components/Login'
import { clearSession, getStoredUser, getToken, type User } from './lib/api'

type View = 'chat' | 'admin'

function App() {
  const [user, setUser] = useState<User | null>(() => (getToken() ? getStoredUser() : null))
  const [view, setView] = useState<View>('chat')

  const logout = useCallback(() => {
    clearSession()
    setUser(null)
    setView('chat')
  }, [])

  if (!user) return <Login onLogin={setUser} />

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
        <span className="muted small user-email">{user.email}</span>
        <button type="button" className="ghost" onClick={logout}>
          로그아웃
        </button>
      </header>
      {view === 'admin' && user.role === 'admin' ? (
        <AdminView />
      ) : (
        <ChatView onAuthError={logout} />
      )}
    </div>
  )
}

export default App
