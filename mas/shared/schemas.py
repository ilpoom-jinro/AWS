from typing import Any

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    namespace: str = "argocd"
    prompt: str | None = None


class ObserveRequest(BaseModel):
    namespace: str = "argocd"


class AnalyzeSignalsRequest(BaseModel):
    namespace: str = "argocd"
    signals: dict[str, Any]
    prompt: str | None = None
