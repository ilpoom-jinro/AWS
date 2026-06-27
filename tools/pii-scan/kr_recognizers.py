"""한국 정형 PII 커스텀 인식기.
- 카드번호는 Presidio 내장 CreditCardRecognizer(Luhn 검증)를 쓰므로 여기 없음.
- 점수는 보수적으로 시작하고 문맥어(context)로 보강해 오탐을 줄임."""
from presidio_analyzer import Pattern, PatternRecognizer


class KrRrnRecognizer(PatternRecognizer):
    """주민등록번호: 정규식 매칭 후 체크섬으로 유효성 확정."""
    def __init__(self, supported_language="ko"):
        patterns = [Pattern(
            "kr_rrn",
            # YYMMDD-GXXXXXX (하이픈/공백 선택). G=1~8(내·외국인/세기 구분)
            r"\b\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[-\s]?[1-8]\d{6}\b",
            0.6,  # 정규식만으로는 신뢰도 보통 → 체크섬 통과 시 validate_result에서 확정
        )]
        super().__init__(
            supported_entity="KR_RRN",
            patterns=patterns,
            context=["주민", "주민등록", "주민번호", "rrn"],
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text):
        # 하이픈/공백 제거 후 13자리만 체크섬 검증
        digits = [c for c in pattern_text if c.isdigit()]
        if len(digits) != 13:
            return None  # 판단 보류 → 정규식 점수(0.6) 유지
        weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
        total = sum(int(d) * w for d, w in zip(digits[:12], weights))
        check = (11 - (total % 11)) % 10
        return check == int(digits[12])  # True=유효(1.0) / False=결과 제거


def build_phone_recognizer(supported_language="ko"):
    """휴대전화번호: 010 등 + 3~4 + 4자리."""
    return PatternRecognizer(
        supported_entity="KR_PHONE",
        patterns=[Pattern("kr_phone", r"\b01[0-9][-\s]?\d{3,4}[-\s]?\d{4}\b", 0.5)],
        context=["전화", "휴대폰", "핸드폰", "연락처", "phone"],
        supported_language=supported_language,
    )


def build_biz_reg_recognizer(supported_language="ko"):
    """사업자등록번호: 3-2-5 형식."""
    return PatternRecognizer(
        supported_entity="KR_BIZ_REG",
        patterns=[Pattern("kr_biz_reg", r"\b\d{3}[-\s]?\d{2}[-\s]?\d{5}\b", 0.4)],
        context=["사업자", "사업자등록", "법인"],
        supported_language=supported_language,
    )


def build_account_recognizer(supported_language="ko"):
    """계좌번호: 은행별 자릿수 편차가 커서 신뢰도 낮게, 문맥어 의존도 높임."""
    return PatternRecognizer(
        supported_entity="KR_ACCOUNT",
        patterns=[Pattern("kr_account",
                          r"\b\d{2,6}[-\s]\d{2,6}[-\s]\d{1,6}(?:[-\s]\d{1,6})?\b", 0.3)],
        context=["계좌", "계좌번호", "입금", "예금주"],
        supported_language=supported_language,
    )
