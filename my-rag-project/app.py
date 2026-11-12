"""ETF 길잡이 — Streamlit 인터페이스 (Frontend). 실행: streamlit run app.py

1. 사이드바에서 PDF를 올리면 rag_module.build_pipeline()이 로드→분할→임베딩→FAISS를 만들고
   "문서 분석 완료"를 띄운다.
2. 하단 채팅창 질문은 RagPipeline.ask()가 검색→프롬프트→GPT-4o→출력(준법 점검·고지)으로 답한다.
"""

import hashlib

import rag_module as rag
import streamlit as st

st.set_page_config(page_title="ETF 길잡이 · 문서 기반 Q&A", page_icon="📈", layout="centered")
st.title("📈 ETF 길잡이")
st.caption(
    "업로드한 ETF 문서(투자설명서·안내서)만 근거로 답하는 RAG 프로토타입입니다. "
    "투자 권유가 아니며, 매수·매도 판단은 하지 않습니다."
)

if "messages" not in st.session_state:
    st.session_state.messages = []  # [{"role", "content", "sources", "meta"}]
    st.session_state.pipeline = None
    st.session_state.signature = None
    st.session_state.total_cost = 0.0
    st.session_state.total_tokens = 0
    st.session_state.n_answers = 0

config_error = rag.check_config()

# ---------------------------------------------------------------------------
# 사이드바: 문서 업로드 · 설정 · 비용
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("1. 문서 업로드")
    files = st.file_uploader(
        "ETF 관련 PDF (여러 개 가능)", type=["pdf"], accept_multiple_files=True
    )
    st.caption("예시 파일: `sample_docs/sample_etf_guide.pdf`")

    st.header("2. 답변 설정")
    level = st.radio("설명 수준", list(rag.LEVEL_GUIDE), horizontal=True)
    chunk_size = st.slider(
        "chunk_size (청크 글자 수)",
        min_value=200,
        max_value=1000,
        value=rag.DEFAULT_CHUNK_SIZE,
        step=50,
        help="작을수록 정확한 위치를 찾지만 맥락이 잘리고, 클수록 맥락은 넓지만 프롬프트 토큰(비용)이 늘어납니다. 바꾸면 문서를 다시 분석합니다.",
    )
    k = st.slider(
        "k (검색할 청크 수)",
        min_value=1,
        max_value=8,
        value=rag.DEFAULT_K,
        help="클수록 근거를 많이 보지만 프롬프트 토큰(비용)과 응답 시간이 늘어납니다.",
    )

    st.header("3. 모델·비용")
    st.caption(f"LLM `{rag.chat_model_name()}` · 임베딩 `{rag.embedding_model_name()}`")
    n = st.session_state.n_answers
    st.metric("누적 LLM 비용 (USD)", f"${st.session_state.total_cost:.4f}")
    st.caption(f"답변 {n}회 · 토큰 {st.session_state.total_tokens:,}개 (임베딩 제외)")
    if n:
        avg = st.session_state.total_cost / n
        monthly = st.number_input("월 예상 문의 수", min_value=0, value=80_000, step=10_000)
        st.caption(f"1회 평균 ${avg:.4f} → 월 예상 약 **${avg * monthly:,.0f}**")
    if st.button("대화 지우기", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

if config_error:
    st.error(config_error)
    st.stop()

# ---------------------------------------------------------------------------
# 문서 분석(1~4단계): 파일 구성이나 chunk_size가 바뀌었을 때만 다시 만든다
# ---------------------------------------------------------------------------
if files:
    payload = [(f.name, f.getvalue()) for f in files]
    digest = hashlib.sha256()
    for name, data in payload:
        digest.update(name.encode())
        digest.update(hashlib.sha256(data).digest())
    signature = (digest.hexdigest(), chunk_size)
    if signature != st.session_state.signature:
        with st.spinner("문서 분석 중… (텍스트 추출 → 분할 → 임베딩 → FAISS 저장)"):
            try:
                st.session_state.pipeline = rag.build_pipeline(payload, chunk_size=chunk_size, k=k)
                st.session_state.signature = signature
            except Exception as e:  # noqa: BLE001 (화면 경계: 텍스트 없는 PDF·키·네트워크 오류를 사용자에게 표시)
                st.session_state.pipeline = None
                st.session_state.signature = None
                st.error(f"문서 분석에 실패했습니다: {type(e).__name__}: {e}")
    if st.session_state.pipeline is not None:
        p = st.session_state.pipeline
        p.k = k  # 검색 개수는 다시 분석하지 않고 바로 반영
        st.success(
            f"문서 분석 완료 · 파일 {len(p.files)}개 · {p.n_pages}쪽 · 청크 {p.n_chunks}개 (chunk_size {p.chunk_size})"
        )
else:
    st.session_state.pipeline = None
    st.session_state.signature = None
    st.info("왼쪽 사이드바에서 ETF 관련 PDF를 업로드하면 문서 분석 후 질문할 수 있어요.")


# ---------------------------------------------------------------------------
# 채팅(5~8단계)
# ---------------------------------------------------------------------------
def render_sources(sources: list[rag.Source]) -> None:
    if not sources:
        return
    cited = [s for s in sources if s.cited] or sources
    with st.expander(f"근거 문서 {len(cited)}건 (검색 {len(sources)}건)"):
        for s in cited:
            st.markdown(f"**[{s.index}] {s.file} · p.{s.page}**")
            st.caption(s.text[:300] + ("…" if len(s.text) > 300 else ""))


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            render_sources(m.get("sources") or [])
            if m.get("meta"):
                st.caption(m["meta"])

question = st.chat_input(
    "문서에 대해 질문하세요 (예: 괴리율이 뭐야?)",
    disabled=st.session_state.pipeline is None,
)
if question:
    history = [
        (q["content"], a["content"])
        for q, a in zip(
            st.session_state.messages[::2], st.session_state.messages[1::2], strict=False
        )
    ]
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("근거를 찾고 답변을 만드는 중…"):
            try:
                res = st.session_state.pipeline.ask(question, level=level, history=history)
            except Exception as e:  # noqa: BLE001 (화면 경계: 인증·한도·네트워크 오류를 사용자에게 표시)
                res = None
                st.error(f"답변 생성에 실패했습니다: {type(e).__name__}: {e}")
        if res is not None:
            st.markdown(res.answer)
            render_sources(res.sources)
            tokens = res.prompt_tokens + res.completion_tokens
            meta = (
                f"{res.elapsed_s:.1f}초 · 토큰 {res.prompt_tokens:,}+{res.completion_tokens:,} "
                f"· ${res.cost_usd:.4f} · 수준 {level}"
                + (" · ⚠️ 준법 점검으로 답변 대체" if res.blocked else "")
            )
            st.caption(meta)
            st.session_state.messages.append(
                {"role": "assistant", "content": res.answer, "sources": res.sources, "meta": meta}
            )
            st.session_state.total_cost += res.cost_usd
            st.session_state.total_tokens += tokens
            st.session_state.n_answers += 1
            st.rerun()  # 사이드바 누적 비용을 바로 갱신(답변은 대화 기록에서 다시 그린다)
        else:
            st.session_state.messages.pop()  # 실패한 질문은 대화 기록에서 뺀다
