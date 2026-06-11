import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
import requests


def env(name, default=None):
    return os.getenv(name, default)


def now_utc():
    return datetime.now(timezone.utc)


def is_placeholder(value):
    return not value or value.startswith("rds-endpoint.example")


def fingerprint(*parts):
    joined = "\n".join(str(part) for part in parts if part is not None)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def request_json(url, params=None, timeout=20):
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def collect_loki_documents(start, end):
    loki_url = env("LOKI_URL", "").rstrip("/")
    if not loki_url:
        return []

    query = env("LOKI_QUERY", '{namespace=~".+"} |~ "(?i)(error|exception|fail|warn)"')
    limit = int(env("LOKI_LIMIT", "100"))
    endpoint = f"{loki_url}/loki/api/v1/query_range"
    payload = request_json(endpoint, {
        "query": query,
        "start": int(start.timestamp() * 1_000_000_000),
        "end": int(end.timestamp() * 1_000_000_000),
        "limit": limit,
        "direction": "backward",
    })

    documents = []
    for stream in payload.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for ts_ns, line in stream.get("values", []):
            observed_at = datetime.fromtimestamp(int(ts_ns) / 1_000_000_000, tz=timezone.utc)
            namespace = labels.get("namespace")
            pod = labels.get("pod")
            container = labels.get("container")
            title = f"Loki log from {namespace or 'unknown'}/{pod or 'unknown'}"
            documents.append({
                "source_type": "log",
                "source_system": "loki",
                "source_id": fingerprint("loki", ts_ns, namespace, pod, container, line),
                "cluster_name": labels.get("cluster"),
                "namespace": namespace,
                "pod_name": pod,
                "service_name": labels.get("service_name") or labels.get("app"),
                "severity": "warning",
                "observed_at": observed_at,
                "title": title,
                "content": line[:6000],
                "metadata": labels,
            })
    return documents


def collect_thanos_documents():
    thanos_url = env("THANOS_QUERY_URL", "").rstrip("/")
    if not thanos_url:
        return []

    queries = json.loads(env("THANOS_QUERIES_JSON", json.dumps([
        {
            "name": "pod_cpu_rate",
            "query": 'sum(rate(container_cpu_usage_seconds_total{container!="",pod!=""}[5m])) by (namespace,pod)',
            "unit": "cpu_cores",
        },
        {
            "name": "pod_memory_working_set",
            "query": 'sum(container_memory_working_set_bytes{container!="",pod!=""}) by (namespace,pod)',
            "unit": "bytes",
        },
    ])))

    documents = []
    for item in queries:
        payload = request_json(f"{thanos_url}/api/v1/query", {"query": item["query"]})
        for result in payload.get("data", {}).get("result", []):
            metric = result.get("metric", {})
            value = result.get("value", [])
            if len(value) != 2:
                continue
            observed_at = datetime.fromtimestamp(float(value[0]), tz=timezone.utc)
            metric_value = value[1]
            namespace = metric.get("namespace")
            pod = metric.get("pod")
            title = f"Thanos metric {item['name']} for {namespace or 'unknown'}/{pod or 'unknown'}"
            content = f"{item['name']}={metric_value} {item.get('unit', '')}".strip()
            documents.append({
                "source_type": "metric",
                "source_system": "thanos",
                "source_id": fingerprint("thanos", item["name"], namespace, pod, observed_at.isoformat(), metric_value),
                "cluster_name": metric.get("cluster"),
                "namespace": namespace,
                "pod_name": pod,
                "service_name": metric.get("service") or metric.get("app"),
                "severity": "info",
                "observed_at": observed_at,
                "title": title,
                "content": content,
                "metadata": {"metric": metric, "query_name": item["name"], "query": item["query"]},
            })
    return documents


def connect_db():
    host = env("RDS_HOST")
    if is_placeholder(host):
        return None
    return psycopg2.connect(
        host=host,
        port=int(env("RDS_PORT", "5432")),
        dbname=env("RDS_DB", "observability"),
        user=env("RDS_USER"),
        password=env("RDS_PASSWORD"),
        connect_timeout=10,
        sslmode=env("RDS_SSLMODE", "require"),
    )


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS observability_documents (
              id BIGSERIAL PRIMARY KEY,
              source_type TEXT NOT NULL,
              source_system TEXT NOT NULL,
              source_id TEXT NOT NULL,
              cluster_name TEXT,
              namespace TEXT,
              pod_name TEXT,
              service_name TEXT,
              severity TEXT,
              observed_at TIMESTAMPTZ NOT NULL,
              title TEXT,
              content TEXT NOT NULL,
              metadata JSONB,
              embedding vector(1536),
              created_at TIMESTAMPTZ DEFAULT now(),
              UNIQUE (source_system, source_id)
            )
        """)
    conn.commit()


def insert_documents(conn, documents):
    if not documents:
        return 0

    rows = [
        (
            doc["source_type"],
            doc["source_system"],
            doc["source_id"],
            doc.get("cluster_name"),
            doc.get("namespace"),
            doc.get("pod_name"),
            doc.get("service_name"),
            doc.get("severity"),
            doc["observed_at"],
            doc.get("title"),
            doc["content"],
            json.dumps(doc.get("metadata", {}), default=str),
        )
        for doc in documents
    ]

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO observability_documents (
              source_type, source_system, source_id, cluster_name, namespace,
              pod_name, service_name, severity, observed_at, title, content, metadata
            )
            VALUES %s
            ON CONFLICT (source_system, source_id) DO NOTHING
        """, rows)
        inserted = cur.rowcount
    conn.commit()
    return inserted


def main():
    end = now_utc()
    start = end - timedelta(minutes=int(env("LOOKBACK_MINUTES", "5")))

    documents = []
    for collector in (collect_loki_documents, collect_thanos_documents):
        try:
            if collector is collect_thanos_documents:
                collected = collector()
            else:
                collected = collector(start, end)
            print(f"{collector.__name__}: {len(collected)} documents")
            documents.extend(collected)
        except Exception as exc:
            print(f"{collector.__name__} failed: {exc}", file=sys.stderr)

    conn = connect_db()
    if conn is None:
        print(f"RDS_HOST is not configured. Dry-run collected {len(documents)} documents.")
        return

    with conn:
        ensure_schema(conn)
        inserted = insert_documents(conn, documents)
    print(f"Inserted {inserted} new documents into Aurora PostgreSQL.")


if __name__ == "__main__":
    main()
