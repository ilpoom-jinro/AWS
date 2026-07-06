"""
SecOps 규정 검색(RAG) 계층 — SecOps 로컬 타입
=============================================
"어떻게 검색하느냐"와 "무엇을 돌려주느냐"를 분리해서, 그 위쪽(map_regulation)이
백엔드 교체에 영향받지 않게 한다.

구현 2개 (같은 인터페이스):
    - LocalRegulationRetriever : 레포 안 규정 발췌 파일을 읽어 검색. AWS 의존성 0.
                                 → 발표 시연용. 발표자 PC에 클론+파이썬만 있으면 동작.
    - BedrockKBRetriever       : 실제 Bedrock Knowledge Base 검색. S3/KB/벡터스토어/IAM 필요.
                                 → 권한 풀리면 env 한 줄로 교체.

교체 방법:
    기본은 Local. 실제 KB로 바꾸려면  USE_BEDROCK_KB=true  (+ BEDROCK_KB_ID).

주의: RetrievedChunk는 map_regulation Activity 내부에서만 쓰이고 Temporal 경계를 넘지 않으므로
      계약 모델이 아니라 가벼운 dataclass로 둔다. (검색 결과는 RegulationMapping에 녹여서 반환)
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

REG_DIR = Path(__file__).parent / "regulations"


@dataclass(frozen=True)
class RetrievedChunk:
    """검색된 규정 근거 한 조각 — 본문 + 출처 + 관련도 점수."""
    text: str
    source: str          # 예: "전자금융감독규정 제13조 (해킹 등 방지대책)"
    score: float         # 0.0 ~ 1.0
    location: str = ""   # 인용 위치(파일#청크 또는 S3 URI 등)


class RegulationRetriever(Protocol):
    """교체형 검색 인터페이스. Local/BedrockKB가 이걸 구현한다."""
    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]: ...


# =====================================================================
# 토큰화 / 점수 (의존성 0 — 발표자 PC에서 추가 설치 불필요)
#   한국어 형태소 분석기 없이 substring 매칭으로 "유출 ⊂ 유출방지", "비정상 ⊂ 비정상적인"
#   같은 부분 일치를 잡는다. 데모엔 충분하고 설명도 쉽다("이 용어들이 근거에 등장").
# =====================================================================
def _tokens(s: str) -> list[str]:
    return re.findall(r"[가-힣]+|[a-zA-Z]+|\d+", s.lower())


def _score(query_terms: list[str], text: str) -> tuple[float, list[str]]:
    uniq = [t for t in dict.fromkeys(query_terms) if len(t) >= 2]
    if not uniq:
        return 0.0, []
    matched = [t for t in uniq if t in text]
    return round(len(matched) / len(uniq), 3), matched


# =====================================================================
# 로컬 구현 (발표 시연용)
# =====================================================================
class LocalRegulationRetriever:
    """레포 안 regulations/*.md를 청크로 쪼개 substring 점수로 검색."""

    def __init__(self, reg_dir: Path = REG_DIR) -> None:
        self._chunks: list[tuple[str, str, str]] = self._load(reg_dir)  # (source, location, text)

    def _load(self, reg_dir: Path) -> list[tuple[str, str, str]]:
        chunks: list[tuple[str, str, str]] = []
        for path in sorted(reg_dir.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            lines = raw.splitlines()
            source = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else path.stem
            body = "\n".join(lines[1:])
            # 빈 줄 기준 청크 분할 (KB 청킹 흉내). 괄호 안내문(데모용...)은 건너뜀
            paras = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("(")]
            for i, para in enumerate(paras):
                chunks.append((source, f"{path.name}#chunk{i}", para))
        return chunks

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        q = _tokens(query)
        scored: list[RetrievedChunk] = []
        for source, loc, text in self._chunks:
            score, _matched = _score(q, text)
            if score > 0:
                scored.append(RetrievedChunk(text=text, source=source, score=score, location=loc))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]


# =====================================================================
# Bedrock Knowledge Base 구현 (권한/리소스 풀리면 교체)
#   같은 인터페이스라 map_regulation은 한 줄도 안 바뀐다.
# =====================================================================
def _source_from_uri(uri: str) -> str:
    """s3://bucket/regulations/efin_supervision_art13.md → efin_supervision_art13"""
    if not uri:
        return ""
    name = uri.rstrip("/").split("/")[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


class BedrockKBRetriever:
    def __init__(self, knowledge_base_id: str | None = None) -> None:
        self._kb_id = knowledge_base_id or os.getenv("BEDROCK_KB_ID", "")

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        import boto3  # lazy

        client = boto3.client(
            "bedrock-agent-runtime",
            region_name=os.getenv("AWS_REGION", "ap-northeast-2"),
        )
        resp = client.retrieve(
            knowledgeBaseId=self._kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": top_k}},
        )
        out: list[RetrievedChunk] = []
        for r in resp.get("retrievalResults", []):
            uri = r.get("location", {}).get("s3Location", {}).get("uri", "")
            meta = r.get("metadata", {}) or {}
            # 출처: 메타데이터 title > S3 파일명 > 기본값 (report의 violated_regulations 가독성)
            source = meta.get("title") or _source_from_uri(uri) or "knowledge-base"
            out.append(RetrievedChunk(
                text=r.get("content", {}).get("text", ""),
                source=source,
                score=round(float(r.get("score", 0.0)), 3),
                location=uri,
            ))
        return out


# =====================================================================
# 팩토리 — env로 백엔드 선택 ("교체는 이 한 줄")
# =====================================================================
@lru_cache(maxsize=1)
def get_retriever() -> RegulationRetriever:
    if os.getenv("USE_BEDROCK_KB", "false").lower() == "true":
        return BedrockKBRetriever()
    return LocalRegulationRetriever()
