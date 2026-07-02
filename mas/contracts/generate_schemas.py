"""
contracts/models.py 의 Pydantic 모델에서 JSON Schema를 자동 생성한다.
schemas/ 디렉터리에 <ModelName>.json 으로 저장.

실행 (mas/ 에서):
    python contracts/generate_schemas.py

모델을 추가하거나 필드를 변경할 때마다 이 스크립트를 다시 실행해
schemas/ 를 최신 상태로 유지한다. 파일을 직접 손으로 편집하지 말 것.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pydantic

from contracts import models

# Mixin/base 클래스는 단독 스키마로 의미 없으므로 제외
_SKIP = {
    "ContractVersionMixin",
    "WorkflowDerivedMixin",
    "WorkflowRootMixin",
    "FinOpsAgentContract",
}

_OUT_DIR = Path(__file__).parent / "schemas"
_OUT_DIR.mkdir(exist_ok=True)


def generate() -> None:
    classes = [
        (name, cls)
        for name, cls in inspect.getmembers(models, inspect.isclass)
        if issubclass(cls, pydantic.BaseModel)
        and not name.startswith("_")
        and cls.__module__ == "contracts.models"
        and name not in _SKIP
    ]

    for name, cls in classes:
        schema = cls.model_json_schema()
        path = _OUT_DIR / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  생성: {path.relative_to(Path(__file__).parent.parent)}")

    print(f"\n총 {len(classes)}개 스키마 생성 완료 → {_OUT_DIR.relative_to(Path(__file__).parent.parent)}/")


if __name__ == "__main__":
    generate()
