"""AWS Bedrock 어댑터(고도화 버전 주 모델·폴백). boto3는 이 파일에서만 쓴다(공통 규칙 1).

- 생성: bedrock-runtime Converse API(모델 공통 형식). LLM_MODEL에 모델 ID 또는 추론 프로필 ID.
- 임베딩: InvokeModel. amazon.titan-embed-text-v2(256/512/1024차원)와 cohere.embed-*를 지원.
- 자격 증명은 boto3 기본 체인(ECS/EC2 IAM 역할 → 환경변수 → ~/.aws)만 쓴다. 키를 받지 않는다.
- boto3는 동기 클라이언트라 asyncio.to_thread로 감싼다. 타임아웃·재시도는 botocore Config로 건다.
"""

import asyncio
import json
import math
from functools import cached_property
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.llm.base import ChatMessage, Embedder, LLMClient, LLMError, LLMResponse
from app.logging import get_logger

log = get_logger(__name__)

_JSON_HINT = "\n\n반드시 JSON 객체 하나만 출력하세요. 설명이나 코드 블록 없이 JSON만 출력합니다."
_EMBED_CONCURRENCY = 8  # Titan은 요청당 1건이라 동시 호출 수를 제한한다
_COHERE_BATCH = 96  # Cohere embed 요청당 최대 텍스트 수


class _BedrockBase:
    def __init__(
        self, *, region: str, profile: str | None, timeout: float, client: Any = None
    ) -> None:
        self._region = region
        self._profile = profile
        self._timeout = timeout
        self._injected = client  # 테스트에서 botocore Stubber를 붙인 클라이언트를 넣는다

    @cached_property
    def _client(self) -> Any:
        if self._injected is not None:
            return self._injected
        try:
            session = boto3.session.Session(profile_name=self._profile, region_name=self._region)
            return session.client(
                "bedrock-runtime",
                config=Config(
                    connect_timeout=5,
                    read_timeout=self._timeout,
                    retries={"max_attempts": 2, "mode": "standard"},
                ),
            )
        except BotoCoreError as e:  # 프로필 없음 등
            raise LLMError(f"Bedrock 클라이언트 생성 실패: {type(e).__name__}") from e

    async def _call(self, op: str, what: str, **kwargs: Any) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(getattr(self._client, op), **kwargs)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "ClientError")
            # 질의 원문은 남기지 않고 오류 코드만 남긴다.
            log.warning("bedrock_call_failed", op=op, model=kwargs.get("modelId"), code=code)
            raise LLMError(f"{what} 실패: {code}") from e
        except BotoCoreError as e:  # 자격 증명 없음·연결·타임아웃
            name = type(e).__name__
            log.warning("bedrock_call_failed", op=op, model=kwargs.get("modelId"), code=name)
            raise LLMError(f"{what} 실패: {name}") from e


def to_converse(
    messages: list[ChatMessage], *, json_mode: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """ChatMessage → Converse (system, messages).

    Converse는 user로 시작해 user/assistant가 번갈아 와야 하므로 같은 역할이 이어지면 합치고,
    맨 앞의 assistant 메시지는 버린다.
    """
    system_text = "\n\n".join(m.content for m in messages if m.role == "system")
    if json_mode:
        system_text = (system_text + _JSON_HINT).strip()
    turns: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system" or not m.content.strip():
            continue
        if not turns and m.role == "assistant":
            continue
        if turns and turns[-1]["role"] == m.role:
            turns[-1]["content"][0]["text"] += "\n\n" + m.content
        else:
            turns.append({"role": m.role, "content": [{"text": m.content}]})
    system = [{"text": system_text}] if system_text else []
    return system, turns


class BedrockLLM(_BedrockBase, LLMClient):
    def __init__(
        self,
        *,
        region: str,
        model_id: str,
        profile: str | None = None,
        timeout: float = 60.0,
        default_max_tokens: int = 800,
        default_temperature: float = 0.2,
        client: Any = None,
    ) -> None:
        super().__init__(region=region, profile=profile, timeout=timeout, client=client)
        self.model = model_id
        self._max_tokens = default_max_tokens
        self._temperature = default_temperature

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        task: str = "generate",
        intent: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        name = model or self.model
        system, turns = to_converse(messages, json_mode=json_mode)
        if not turns:
            raise LLMError("Bedrock 호출 실패: 사용자 메시지가 없습니다")
        req: dict[str, Any] = {
            "modelId": name,
            "messages": turns,
            "inferenceConfig": {
                "maxTokens": max_tokens or self._max_tokens,
                "temperature": self._temperature if temperature is None else temperature,
            },
        }
        if system:
            req["system"] = system
        resp = await self._call("converse", "Bedrock 호출", **req)
        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        # 추론형 모델의 reasoningContent 블록은 버리고 text만 쓴다.
        text = "".join(b["text"] for b in blocks if "text" in b).strip()
        u = resp.get("usage") or {}
        usage = {}
        if u:
            usage = {
                "prompt_tokens": u.get("inputTokens", 0),
                "completion_tokens": u.get("outputTokens", 0),
            }
        return LLMResponse(text=text, model=name, usage=usage)


class BedrockEmbedder(_BedrockBase, Embedder):
    def __init__(
        self,
        *,
        region: str,
        model_id: str,
        dim: int,
        profile: str | None = None,
        timeout: float = 60.0,
        client: Any = None,
    ) -> None:
        super().__init__(region=region, profile=profile, timeout=timeout, client=client)
        self.model = model_id
        self.dim = dim
        if not (model_id.startswith("amazon.titan-embed") or model_id.startswith("cohere.embed")):
            raise ValueError(f"지원하지 않는 Bedrock 임베딩 모델: {model_id}")

    async def _invoke(self, body: dict[str, Any]) -> dict[str, Any]:
        resp = await self._call(
            "invoke_model",
            "Bedrock 임베딩",
            modelId=self.model,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        raw = resp["body"]
        return json.loads(raw.read() if hasattr(raw, "read") else raw)

    async def _titan(self, texts: list[str]) -> list[list[float]]:
        sem = asyncio.Semaphore(_EMBED_CONCURRENCY)

        async def one(t: str) -> list[float]:
            async with sem:
                out = await self._invoke(
                    {"inputText": t, "dimensions": self.dim, "normalize": True}
                )
            return out["embedding"]

        return list(await asyncio.gather(*(one(t) for t in texts)))

    async def _cohere(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), _COHERE_BATCH):
            out = await self._invoke(
                {
                    "texts": texts[i : i + _COHERE_BATCH],
                    # 인터페이스가 문서/질의를 구분하지 않아 문서용으로 통일한다.
                    "input_type": "search_document",
                    "embedding_types": ["float"],
                }
            )
            emb = out["embeddings"]
            vectors.extend(emb["float"] if isinstance(emb, dict) else emb)
        return vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        is_titan = self.model.startswith("amazon.titan-embed")
        vectors = await (self._titan(texts) if is_titan else self._cohere(texts))
        for v in vectors:
            if len(v) != self.dim:
                raise LLMError(
                    f"임베딩 차원 불일치: 모델 {self.model}={len(v)}, EMBEDDING_DIM={self.dim}"
                )
        return [_normalize(v) for v in vectors]


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]
