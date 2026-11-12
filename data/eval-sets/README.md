# eval-sets

`make eval`(ml/eval)이 읽는 오프라인 평가 세트. 지금 파일은 **형식 예시 10줄씩**이고 본 데이터는 팀이 채운다.
모든 질문은 `data/samples`의 샘플 ETF·문서를 기준으로 한다.

| 파일 | 지표 | 필드 |
| --- | --- | --- |
| `golden.jsonl` | 답변 정확도: 기대 키워드·수치가 모두 답변에 있으면 정답 | `id`, `question`, `level?`, `expected_intents`, `expected_keywords[]`, `expected_numbers[]` |
| `intents.jsonl` | 의도 분류 정확도(집합 일치) | `question`, `intents[]` |
| `aliases.jsonl` | ETF명 인식 마이크로 F1 | `question`, `tickers[]` |
| `violations.jsonl` | 위반 탐지 재현율(+ 오탐률) | `text`, `should_block`, `category` |
