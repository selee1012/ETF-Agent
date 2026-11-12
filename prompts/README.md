# prompts

에이전트·가드 프롬프트와 규칙을 버전 관리하는 곳. 코드 변경 없이 문구를 고칠 수 있다(로컬에서는 api가 자동 리로드).

| 경로 | 쓰는 곳 | 설명 |
| --- | --- | --- |
| `system/classifier.md` | 오케스트레이터(P1-AG-02) | 의도 분류 JSON 지시 |
| `system/answer_{beginner,intermediate,expert}.md` | 답변 합성(P1-AG-06) | 설명 수준별 역할·구성·분량·형식 예시 |
| `system/answer_rules.md` | 답변 합성 | 입력 자료([ETF 데이터]·[공시]·[근거 N]) 설명, 작성 순서, 공통 규칙. 수준별 파일 뒤에 붙는다 |
| `system/general.md` | 일반 대화(로컬 전용) | 근거 없는 자유 답변 |
| `guard/rules.yaml` | 가드 ①(P1-AG-06) | 금칙 표현 정규식, 근거 수치 검사 설정 |
| `guard/disclaimers.yaml` | 가드 ①·합성 | 의도별 필수 고지 |
| `guard/judge.md` | 가드 ② | 검증 모델 JSON 판정 지시 |
| `templates/high_risk/*.md` | 가드 ③ | 고위험 의도 고정 답변(준법감시 승인 전 초안) |
| `templates/*.md` | 그래프 | 추천(Phase 3 안내)·범위 밖·안전 답변 |

템플릿의 `{inquiry_channel}`은 설정값 `INQUIRY_CHANNEL`로 바뀐다.
