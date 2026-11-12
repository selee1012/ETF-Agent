# prompts

에이전트·가드 프롬프트와 규칙을 버전 관리하는 곳. 코드 변경 없이 문구를 고칠 수 있다(로컬에서는 api가 자동 리로드).

| 경로 | 쓰는 곳 | 설명 |
| --- | --- | --- |
| `system/classifier.md` | 오케스트레이터(P1-AG-02) | 의도 분류 JSON 지시 |
| `system/faq_{beginner,intermediate,expert}.md` | FAQ 에이전트(P1-AG-04) | 설명 수준별 시스템 프롬프트 |
| `system/etf_summary.md` | ETF 정보 에이전트(P1-AG-03) | DB 표를 한두 문장으로 요약 |
| `system/disclosure_summary.md` | 공시 요약 에이전트(P1-AG-05) | 공시 목록 요약 |
| `guard/rules.yaml` | 가드 ①(P1-AG-06) | 금칙 표현 정규식, 근거 수치 검사 설정 |
| `guard/disclaimers.yaml` | 가드 ①·합성 | 의도별 필수 고지 |
| `guard/judge.md` | 가드 ② | 검증 모델 JSON 판정 지시 |
| `templates/high_risk/*.md` | 가드 ③ | 고위험 의도 고정 답변(준법감시 승인 전 초안) |
| `templates/*.md` | 그래프 | 추천(Phase 3 안내)·범위 밖·안전 답변 |

템플릿의 `{inquiry_channel}`은 설정값 `INQUIRY_CHANNEL`로 바뀐다.
