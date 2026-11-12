"""문단 기준 청킹(겹침 포함). # P1-DA-03"""

import re
from dataclasses import dataclass, field
from typing import Any

MAX_CHARS = 700
OVERLAP_CHARS = 200

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(slots=True)
class TextChunk:
    content: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Section:
    heading: str | None
    paragraphs: list[str]
    page: int | None = None


def parse_markdown(text: str) -> tuple[str | None, list[Section]]:
    """(문서 제목, 섹션 목록). 제목은 첫 '# ' 헤딩."""
    title: str | None = None
    sections: list[Section] = [Section(heading=None, paragraphs=[])]
    buf: list[str] = []

    def flush() -> None:
        if buf:
            para = " ".join(s.strip() for s in buf).strip()
            if para:
                sections[-1].paragraphs.append(para)
            buf.clear()

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level, heading = len(m.group(1)), m.group(2)
            if level == 1 and title is None:
                title = heading
                continue
            sections.append(Section(heading=heading, paragraphs=[]))
        elif not line.strip():
            flush()
        elif line.lstrip().startswith(("- ", "* ", "> ")):
            # 목록·인용은 한 줄씩 문단 경계로 본다
            flush()
            buf.append(line.lstrip()[2:])
            flush()
        else:
            buf.append(line)
    flush()
    return title, [s for s in sections if s.paragraphs]


def parse_plain_pages(pages: list[str]) -> list[Section]:
    out = []
    for i, page in enumerate(pages, start=1):
        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", page)]
        paras = [p for p in paras if p]
        if paras:
            out.append(Section(heading=None, paragraphs=paras, page=i))
    return out


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?다])\s+", paragraph)
    out, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > max_chars:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    # 문장 하나가 max보다 길면 글자 단위로 자른다
    return [p[i : i + max_chars] for p in out for i in range(0, len(p), max_chars)]


def chunk_sections(
    sections: list[Section], *, max_chars: int = MAX_CHARS, overlap_chars: int = OVERLAP_CHARS
) -> list[TextChunk]:
    """섹션 안에서 문단을 max_chars까지 모으고, 다음 청크는 직전 청크 끝 문단(겹침)으로 시작한다."""
    chunks: list[TextChunk] = []
    for sec in sections:
        paras = [p for para in sec.paragraphs for p in _split_long(para, max_chars)]
        cur: list[str] = []
        for para in paras:
            if cur and sum(len(p) + 1 for p in cur) + len(para) > max_chars:
                chunks.append(_make(sec, cur))
                tail = cur[-1]
                cur = [tail[-overlap_chars:]] if overlap_chars > 0 else []
            cur.append(para)
        if cur:
            chunks.append(_make(sec, cur))
    return chunks


def _make(sec: Section, paras: list[str]) -> TextChunk:
    body = "\n".join(paras)
    content = f"## {sec.heading}\n{body}" if sec.heading else body
    meta: dict[str, Any] = {}
    if sec.heading:
        meta["heading"] = sec.heading
    if sec.page is not None:
        meta["page"] = sec.page
    return TextChunk(content=content, meta=meta)
