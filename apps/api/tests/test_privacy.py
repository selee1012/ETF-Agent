"""개인정보 마스킹(P1-AG-06, 공통 규칙 4)."""

import pytest

from app.privacy import find_pii, mask_pii


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("연락처 010-1234-5678", "PHONE"),
        ("01012345678로 연락", "PHONE"),
        ("메일 hong.gildong@example.com", "EMAIL"),
        ("주민번호 900101-1234567", "RRN"),
        ("계좌 110-123-456789", "ACCOUNT"),
        ("카드 1234-5678-9012-3456", "CARD"),
    ],
)
def test_masks_pii(text: str, kind: str) -> None:
    masked = mask_pii(text)
    assert f"[{kind}]" in masked
    assert kind in find_pii(text)


def test_keeps_non_pii_numbers() -> None:
    text = "기준일 2026-11-11, 종목코드 900010, 괴리율 0.23%, 문의 1588-0000"
    assert mask_pii(text) == text
    assert find_pii(text) == []
