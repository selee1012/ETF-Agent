// 설명 수준 표시 문구(온보딩·프로필·상단바). # P1-API-01
import type { Level } from './api'

export const LEVELS: { value: Level; label: string; who: string; how: string }[] = [
  {
    value: 'beginner',
    label: '입문',
    who: 'ETF를 처음 접해요',
    how: '어려운 용어를 풀어 쓰고, 비유와 예시로 차근차근 설명해요.',
  },
  {
    value: 'intermediate',
    label: '중급',
    who: '기본 개념은 알고 있어요',
    how: '핵심 원리와 상품 간 비교 포인트를 중심으로 설명해요.',
  },
  {
    value: 'expert',
    label: '숙련',
    who: 'ETF 투자 경험이 많아요',
    how: '구조·수치·세부 조건 위주로 간결하게 설명해요.',
  },
]

export const levelLabel = (level: Level | null) =>
  LEVELS.find((l) => l.value === level)?.label ?? '미설정'
