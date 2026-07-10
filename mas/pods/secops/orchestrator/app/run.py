"""
run.py — SecOps 컨테이너 진입점 (Worker + Poller + HTTP API 병행 실행)
======================================================================
한 컨테이너에서 세 가지를 함께 띄운다 (AIOps run.py 패턴):
  1. Temporal Worker      (worker.main) — Activity/Workflow 실행 + SQS poller
  2. HTTP API             (api.app)     — UI 조회/수동 실행 + /health (uvicorn)

worker.main()은 내부에서 SQS poller까지 함께 돈다. 여기에 uvicorn(API)을
같은 asyncio 이벤트 루프에서 병행 실행한다. 어느 한쪽이 죽으면 프로세스를
종료해(파드 재시작 유도) 반쪽 상태로 남지 않게 한다.

이 API 서버가 /health를 제공하므로 배포에서 HTTP 프로브 사용이 가능해진다.
"""
from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

from .api import app as api_app
from .worker import main as worker_main

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("secops.run")

API_PORT = int(os.getenv("API_PORT", "8000"))


async def _run_api_server() -> None:
    config = uvicorn.Config(api_app, host="0.0.0.0", port=API_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    logger.info("SecOps 컨테이너 시작 — Worker(+poller) + HTTP API 병행")
    worker_task = asyncio.create_task(worker_main(), name="temporal-worker")
    api_task = asyncio.create_task(_run_api_server(), name="http-api")

    done, pending = await asyncio.wait(
        {worker_task, api_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in done:
        exc = task.exception()
        logger.error("%s 종료됨%s", task.get_name(), f" (예외: {exc})" if exc else " (정상)")
    for task in pending:
        task.cancel()
    for task in done:
        if task.exception():
            raise task.exception()


if __name__ == "__main__":
    asyncio.run(main())
