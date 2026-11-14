# eval-sets

`make eval`(ml/eval)이 읽는 오프라인 평가 세트. 지금 파일은 **형식 예시 10~15줄씩**이고 본 데이터는 팀이 채운다.
모든 질문은 `data/samples`의 샘플 ETF·문서를 기준으로 한다.

| 파일 | 지표 | 필드 |
| --- | --- | --- |
| `golden.jsonl` | 답변 정확도: 기대 키워드·수치가 모두 답변에 있고 분류된 의도가 `expected_intents`와 같으면 정답 | `id`, `question`, `level?`, `expected_intents`, `expected_keywords[]`, `expected_numbers[]` |
| `intents.jsonl` | 의도 분류 정확도(집합 일치) | `question`, `intents[]` |
| `aliases.jsonl` | ETF명 인식 마이크로 F1 | `question`, `tickers[]` |
| `violations.jsonl` | 위반 탐지 재현율(+ 오탐률). 금칙 표현·개인정보 규칙으로 판정하고 `--with-judge`를 주면 검증 모델의 권유 판정을 더한다 | `text`, `should_block`, `category`(사람이 읽는 분류, 채점에는 쓰지 않음) |

의도 분류는 그래프 전체를 돌려 채점한다. 일반 대화 모드(`GENERAL_CHAT_ENABLED=true`)에서는 범위 밖 질문이 `general`로 바뀌어 `out_of_scope` 행이 오답이 되므로 끄고 돌린다.
