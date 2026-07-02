"""
run.py — AIOps 컨테이너 진입점 (Worker + Alert Trigger 병행 실행)
===================================================================
한 컨테이너에서 두 가지를 함께 띄운다:
  1. Temporal Worker (worker.main)     — Activity/Workflow 실행 (Temporal 폴링)
  2. Alertmanager webhook 수신 (trigger.app) — 이벤트 → 워크플로 시작 (HTTP)

둘은 각각 Temporal 폴링 / HTTP 수신이라 성격이 다르므로, 하나의
asyncio 이벤트 루프에서 동시 실행한다. 어느 한쪽이 죽으면 프로세스를
종료해(파드 재시작 유도) 반쪽 상태로 남지 않게 한다.
"""
from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

from .trigger import app as trigger_app
from .worker import main as worker_main

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aiops.run")

TRIGGER_PORT = int(os.getenv("TRIGGER_PORT", "8080"))


async def _run_trigger_server() -> None:
    """Alertmanager webhook 수신용 uvicorn 서버를 async로 실행."""
    config = uvicorn.Config(
        trigger_app,
        host="0.0.0.0",
        port=TRIGGER_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    logger.info("AIOps 컨테이너 시작 — Worker + Alert Trigger 병행")
    worker_task = asyncio.create_task(worker_main(), name="temporal-worker")
    trigger_task = asyncio.create_task(_run_trigger_server(), name="alert-trigger")

    # 둘 중 하나라도 종료되면(정상/예외 불문) 전체를 정리해 파드를 재시작시킨다.
    done, pending = await asyncio.wait(
        {worker_task, trigger_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in done:
        exc = task.exception()
        if exc:
            logger.error("%s 종료됨 (예외): %s", task.get_name(), exc)
        else:
            logger.error("%s 종료됨 (정상)", task.get_name())
    for task in pending:
        task.cancel()
    # 예외가 있었으면 non-zero 종료를 위해 다시 던진다.
    for task in done:
        if task.exception():
            raise task.exception()


if __name__ == "__main__":
    asyncio.run(main())
