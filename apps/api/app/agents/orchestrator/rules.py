"""키워드 규칙 의도 분류(LLM JSON 파싱 실패 시 대체, 고위험은 항상 우선 검사). # P1-AG-02"""

import re

from app.agents.state import Intent

_P = lambda *xs: [re.compile(x, re.IGNORECASE) for x in xs]  # noqa: E731

HIGH_RISK = _P(
    r"(언제|지금|어느\s*시점|타이밍|시기).{0,12}(사|팔|매수|매도|들어가|진입|정리|손절|익절)",
    r"(사야|팔아야|살까|팔까|사도\s*(될|돼|되)|팔아도\s*(될|돼|되)|사는\s*게\s*(좋|나)|파는\s*게\s*(좋|나))",
    r"(매수|매도|진입)\s*(타이밍|시점|적기)",
    r"(오를까|내릴까|떨어질까|오르겠|떨어지겠|오를\s*것\s*같|폭락|급등)",
    r"(수익률|가격|주가).{0,6}(예측|예상|전망)|전망\s*(어때|은|이)|얼마나\s*(오를|벌|수익)|목표\s*(가|주가)",
    r"(내|제|저의|나의|우리).{0,15}(세금|양도세|배당소득세|종합과세|건보료).{0,10}(얼마|계산|나와|내야)",
    r"세금\s*(얼마|계산해)",
    r"(손실|손해).{0,12}(보상|보전|물어|책임져|배상|돌려)",
)
RECOMMEND = _P(
    r"추천",
    r"골라\s*(줘|주세요)",
    r"뭐\s*(사|살|담)",
    r"(어떤|어느)\s*(etf|이티에프|상품|거).{0,10}(좋|사|살|괜찮|나아)",
    r"포트폴리오\s*(짜|구성|만들)",
)
DISCLOSURE = _P(r"공시", r"뉴스", r"소식", r"발표", r"이슈", r"리포트")
ETF_INFO = _P(
    r"괴리율",
    r"시세",
    r"가격",
    r"종가",
    r"nav|순자산",
    r"거래량",
    r"보수",
    r"비교",
    r"기초\s*지수",
    r"운용사",
    r"상장일",
    r"추이",
)
SEARCH = _P(
    r"찾아\s*(줘|주세요)|검색|목록|리스트|어떤\s*것들|종류.{0,6}(있|알려)|이하|미만|이상",
    r"etf\s*들",
)
FAQ_DEF = _P(
    r"(이란|란\s*(뭐|무엇)|뭐야|뭔가요|뭐예요|뭐에요|무엇|뜻|개념|정의|의미|원리|차이|설명해)",
    r"어떻게\s*(돼|되|작동|계산|받|사|거래)",
    r"(왜|방법|주의할|위험)",
    r"(언제|며칠).{0,6}(받|주|지급|들어)",
    r"(되나요|인가요|있나요|하나요|해야\s*하나)",
)
DOMAIN = _P(
    r"etf|이티에프|상장지수|펀드|투자|분배금|배당|세금|과세|지수|채권|레버리지|인버스|lp|ap|추적",
    r"주식|증권|계좌|호가|매매|수수료|보수|괴리|nav",
)


def _any(pats: list[re.Pattern[str]], text: str) -> bool:
    return any(p.search(text) for p in pats)


def is_high_risk(text: str) -> bool:
    return _any(HIGH_RISK, text)


def classify_rules(text: str, *, has_entity: bool) -> list[str]:
    if is_high_risk(text):
        return [Intent.HIGH_RISK]
    if _any(RECOMMEND, text):
        return [Intent.RECOMMENDATION]

    intents: list[str] = []
    info_kw, faq_kw = _any(ETF_INFO, text), _any(FAQ_DEF, text)
    if has_entity:
        if info_kw or not (faq_kw or _any(DISCLOSURE, text)):
            intents.append(Intent.ETF_INFO)
        if faq_kw and not info_kw:
            intents.append(Intent.FAQ)
    elif _any(SEARCH, text) and (info_kw or _any(DOMAIN, text)):
        intents.append(Intent.ETF_INFO)
    if _any(DISCLOSURE, text):
        intents.append(Intent.DISCLOSURE)
    if not intents and (faq_kw or info_kw or _any(DOMAIN, text)):
        intents.append(Intent.FAQ)
    return intents or [Intent.OUT_OF_SCOPE]


def is_domain(text: str) -> bool:
    """ETF·투자 관련 표현이 있는지(일반 대화 모드에서 '저녁 메뉴 추천' 같은 질문을 가려낸다)."""
    return _any(DOMAIN, text)


def is_followup_info(text: str) -> bool:
    """'그럼 괴리율은?'처럼 정의 질문이 아닌 정보 항목만 묻는 후속 질문."""
    return _any(ETF_INFO, text) and not _any(FAQ_DEF, text)
