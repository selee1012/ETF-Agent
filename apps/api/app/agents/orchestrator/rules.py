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
# 위험 요청: 탐지 즉시 차단(LLM을 부르지 않는다). 사유('허가받았다', '교육 목적')와 무관하게 막는다. # P1-AG-06
BLOCKED = _P(
    # 해킹·보안 공격
    r"해킹|크래킹|모의\s*침투|침투\s*테스트|펜\s*테스트|pen\s*test|익스플로잇|exploit",
    r"취약점.{0,12}(점검|찾|스캔|공격|분석|진단|뚫)|보안.{0,6}(뚫|우회|무력화)",
    r"sql\s*(인젝션|injection)|xss|csrf|ddos|디도스|랜섬웨어|악성\s*코드|멀웨어|malware|백도어|키로거",
    r"피싱\s*(사이트|메일|페이지).{0,10}(만들|제작)|무차별\s*대입|brute\s*force",
    r"(비밀번호|패스워드|암호|계정|관리자\s*권한).{0,10}(뚫|크랙|탈취|알아내|훔)",
    r"(개인정보|고객\s*정보|데이터베이스|db|디비|서버).{0,10}(탈취|빼내|털어|털고|유출시|침입|뚫)",
    # 프롬프트 인젝션·지침 무력화
    r"(이전|위의?|앞의?|기존|모든|지금까지).{0,8}(지시|지침|명령|규칙|프롬프트|설정).{0,12}(무시|잊어|따르지|버려|초기화|삭제)",
    r"ignore.{0,30}(instruction|prompt|rule)|disregard.{0,30}(instruction|prompt|rule)",
    r"시스템\s*프롬프트|system\s*prompt|개발자\s*모드|developer\s*mode|jailbreak|탈옥|프롬프트\s*인젝션",
    r"(프롬프트|지침|지시문|내부\s*설정|초기\s*설정).{0,10}(보여|알려|출력|공개|말해|뭐야|뭐니|유출)",
    r"(제한|제약|필터|검열|안전\s*장치|규칙).{0,6}(없이|해제하고|풀고|끄고|무시하고|우회해서).{0,12}(답|대답|말해|알려|응답|출력)",
    r"(지금부터|이제부터)\s*(너는|넌|당신은)|너는\s*(이제|지금부터)",
    # 그 밖의 명백한 불법·위해
    r"(폭탄|폭발물|마약|총기|독극물).{0,10}(만들|제조|구하|구입|사는)",
    r"(주가|시세)\s*(조작|조종).{0,10}(방법|하는\s*법|하려면|알려|해줘)|작전\s*세력.{0,10}(방법|하는\s*법)",
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


def is_blocked(text: str) -> bool:
    return _any(BLOCKED, text)


def classify_rules(text: str, *, has_entity: bool) -> list[str]:
    if is_blocked(text):
        return [Intent.BLOCKED]
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


def is_search(text: str) -> bool:
    """'찾아줘'·'목록'·'이하'처럼 조건으로 상품을 찾는 표현이 있는지."""
    return _any(SEARCH, text)


def is_followup_info(text: str) -> bool:
    """'그럼 괴리율은?'처럼 정의 질문이 아닌 정보 항목만 묻는 후속 질문."""
    return _any(ETF_INFO, text) and not _any(FAQ_DEF, text)
