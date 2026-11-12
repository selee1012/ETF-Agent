// 인증 모드: VITE_AUTH_MODE=local(dev-login) | supabase(나중 구현)
import { devLogin, type User } from './api'

export const AUTH_MODE = import.meta.env.VITE_AUTH_MODE ?? 'local'

export async function login(email: string): Promise<User> {
  if (AUTH_MODE === 'supabase') {
    // Phase 1 배포: @supabase/supabase-js로 로그인 후 access_token을 saveSession()에 넣는다.
    throw new Error('Supabase 로그인은 아직 구현되지 않았습니다 (VITE_AUTH_MODE=local 사용)')
  }
  return devLogin(email)
}
