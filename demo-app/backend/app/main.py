import os
import time
from contextlib import contextmanager
from datetime import date
from typing import Generator

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.aws import AwsXRayPropagator
from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel, ConfigDict


class Recommendation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    ticker: str
    currentPrice: int
    recommendedPrice: int
    recommendationDate: date


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


DATABASE_URL = (
    f"postgresql://{env('DB_USER', 'stockuser')}:"
    f"{env('DB_PASSWORD', 'stockpass')}@"
    f"{env('DB_HOST', 'localhost')}:"
    f"{env('DB_PORT', '5432')}/"
    f"{env('DB_NAME', 'stockdemo')}"
)

app = FastAPI(title="Stock Recommendation Demo API")

if env_bool("OTEL_TRACING_ENABLED"):
    resource = Resource.create(
        {
            "service.name": env("OTEL_SERVICE_NAME", "stock-demo-api"),
            "deployment.environment": env("DEPLOYMENT_ENVIRONMENT", "demo"),
        }
    )

    trace.set_tracer_provider(
        TracerProvider(
            id_generator=AwsXRayIdGenerator(),
            resource=resource,
        )
    )
    trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter())
    )
    set_global_textmap(AwsXRayPropagator())
    FastAPIInstrumentor.instrument_app(app)

tracer = trace.get_tracer("stock-demo-api")

cors_origins = [
    origin.strip()
    for origin in env("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn


@contextmanager
def trace_subsegment(name: str) -> Generator[None, None, None]:
    if not env_bool("OTEL_TRACING_ENABLED"):
        yield
        return

    with tracer.start_as_current_span(
        name,
        attributes={
            "db.system": "postgresql",
            "db.name": env("DB_NAME", "stockdemo"),
            "db.operation": "SELECT",
        },
    ):
        yield


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/demo/bad-request")
def demo_bad_request() -> dict[str, str]:
    raise HTTPException(
        status_code=400,
        detail="Demo 400 error: invalid stock recommendation request.",
    )


@app.get("/api/demo/server-error")
def demo_server_error() -> dict[str, str]:
    raise RuntimeError("Demo 500 error: simulated backend failure.")


@app.get("/api/demo/slow")
def demo_slow_response() -> dict[str, str]:
    with tracer.start_as_current_span("Demo slow operation"):
        time.sleep(1.2)
    return {"status": "slow", "message": "Demo slow response completed."}


@app.get("/api/recommendations", response_model=list[Recommendation])
def list_recommendations() -> list[Recommendation]:
    query = """
        SELECT
          id,
          name,
          ticker,
          current_price,
          recommended_price,
          recommendation_date
        FROM recommendations
        ORDER BY recommendation_date DESC, id ASC;
    """

    with trace_subsegment("PostgreSQL SELECT recommendations"):
        with get_connection() as conn:
            rows = conn.execute(query).fetchall()

    return [
        Recommendation(
            id=row[0],
            name=row[1],
            ticker=row[2],
            currentPrice=row[3],
            recommendedPrice=row[4],
            recommendationDate=row[5],
        )
        for row in rows
    ]
