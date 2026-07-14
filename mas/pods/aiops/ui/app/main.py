import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


ORCHESTRATOR_URL = os.getenv(
    "ORCHESTRATOR_URL",
    "http://aiops-orchestrator.aiops-mas.svc.cluster.local",
)
ORCHESTRATOR_TIMEOUT_SECONDS = int(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "30"))
TEMPORAL_UI_URL = os.getenv(
    "TEMPORAL_UI_URL",
    "https://temporal-ui.teleport.local",
)

app = FastAPI(title="AIOps MAS Control", version="0.1.0")


class RunWorkflowRequest(BaseModel):
    cluster_name: str
    namespace: str
    workflow_id: str | None = None


def call_orchestrator(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = Request(f"{ORCHESTRATOR_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"orchestrator timeout: {exc}") from exc
    except URLError as exc:
        raise HTTPException(status_code=503, detail=f"orchestrator unavailable: {exc}") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard() -> Any:
    return call_orchestrator("/api/dashboard")


@app.get("/api/clusters/{cluster_name}/namespaces")
def cluster_namespaces(cluster_name: str) -> Any:
    return call_orchestrator(f"/api/clusters/{cluster_name}/namespaces")


@app.post("/api/workflows/run")
def run_workflow(request: RunWorkflowRequest) -> Any:
    return call_orchestrator(
        "/api/workflows/run",
        method="POST",
        body=request.model_dump(),
    )


@app.get("/api/workflows/{workflow_id}")
def workflow_detail(workflow_id: str) -> Any:
    return call_orchestrator(f"/api/workflows/{workflow_id}")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return f"""
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>AIOps MAS Control</title>
    <style>
      :root {{
        --bg: #f7f9fc;
        --panel: #ffffff;
        --line: #d8e0ea;
        --text: #172033;
        --muted: #68758c;
        --blue: #4d65f4;
        --blue-soft: #eaf0ff;
        --green: #108a57;
        --red: #c53b3b;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 18px 22px;
        border-bottom: 1px solid var(--line);
        background: var(--panel);
      }}
      h1 {{ margin: 0; font-size: 24px; line-height: 1.1; }}
      .sub {{ color: var(--muted); margin-top: 3px; }}
      main {{ padding: 18px; display: grid; gap: 18px; }}
      .summary {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 16px;
      }}
      .label {{ color: var(--muted); font-size: 14px; margin-bottom: 8px; }}
      .value {{ font-size: 24px; font-weight: 800; }}
      .layout {{
        display: grid;
        grid-template-columns: 420px minmax(0, 1fr);
        gap: 18px;
      }}
      .watch-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
      }}
      .watch-item {{
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fbfdff;
        padding: 14px;
        min-height: 130px;
      }}
      .watch-title {{
        color: var(--muted);
        font-size: 14px;
        margin-bottom: 9px;
      }}
      .watch-status {{
        font-size: 22px;
        font-weight: 800;
        margin-bottom: 7px;
      }}
      .watch-meta {{
        color: var(--muted);
        font-size: 13px;
        white-space: pre-wrap;
      }}
      .watch-item.ok {{
        border-color: #b9dfcc;
        background: #f3fbf7;
      }}
      .watch-item.alert {{
        border-color: #f0b6b6;
        background: #fff6f6;
      }}
      .watch-item.pending {{
        border-color: #c8d3ff;
        background: #f6f8ff;
      }}
      .panel {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 18px;
      }}
      h2 {{ font-size: 18px; margin: 0 0 14px; }}
      label {{ display: block; font-weight: 700; margin: 14px 0 6px; }}
      select, input, textarea {{
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 11px 12px;
        background: #fff;
        color: var(--text);
        font: inherit;
      }}
      button {{
        border: 0;
        border-radius: 8px;
        padding: 12px 16px;
        background: var(--blue);
        color: white;
        font-weight: 800;
        cursor: pointer;
      }}
      button:disabled {{ cursor: not-allowed; opacity: 0.55; }}
      .actions {{ display: flex; gap: 10px; margin-top: 18px; }}
      .secondary {{ background: #e8edf6; color: var(--text); }}
      .segmented {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }}
      .segment {{
        min-height: 46px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fff;
        color: var(--text);
        padding: 10px 12px;
      }}
      .segment.active {{
        border-color: var(--blue);
        background: var(--blue);
        color: #fff;
      }}
      .namespace-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .timeline {{ display: grid; gap: 10px; }}
      .step {{
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 13px 14px;
        display: flex;
        justify-content: space-between;
        gap: 14px;
      }}
      .badge {{
        align-self: start;
        border-radius: 999px;
        padding: 4px 9px;
        background: var(--blue-soft);
        color: #3150b8;
        font-size: 12px;
        font-weight: 800;
        white-space: nowrap;
      }}
      .result {{
        min-height: 128px;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px;
        background: #fbfdff;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }}
      .result-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
      }}
      .result-card {{
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fbfdff;
        padding: 14px;
        min-height: 132px;
      }}
      .result-card h3 {{
        margin: 0 0 10px;
        font-size: 15px;
      }}
      .result-card pre {{
        margin: 0;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        font: inherit;
      }}
      .incident-banner {{
        margin-top: 14px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fbfdff;
        padding: 16px;
        min-height: 86px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
      }}
      .incident-title {{
        color: var(--muted);
        font-size: 14px;
        margin-bottom: 6px;
      }}
      .incident-message {{
        font-size: 24px;
        font-weight: 800;
      }}
      .incident-banner.ok {{
        border-color: #b9dfcc;
        background: #f3fbf7;
      }}
      .incident-banner.alert {{
        border-color: #f0b6b6;
        background: #fff6f6;
      }}
      .incident-banner.pending {{
        border-color: #c8d3ff;
        background: #f6f8ff;
      }}
      .incident-chip {{
        border-radius: 999px;
        padding: 6px 10px;
        background: #e8edf6;
        color: var(--muted);
        font-size: 12px;
        font-weight: 800;
        white-space: nowrap;
      }}
      .ok {{ color: var(--green); }}
      .err {{ color: var(--red); }}
      .pending-text {{ color: #3150b8; }}
      a {{ color: #3150b8; font-weight: 700; text-decoration: none; }}
      @media (max-width: 900px) {{
        .summary, .watch-grid, .layout, .result-grid {{ grid-template-columns: 1fr; }}
        header {{ align-items: flex-start; flex-direction: column; }}
      }}
    </style>
  </head>
  <body>
    <header>
      <div>
        <h1>AIOps MAS Control</h1>
        <div class="sub">Incident detection first, remediation after approval.</div>
      </div>
      <button id="refreshButton" class="secondary">새로고침</button>
    </header>
    <main>
      <section class="summary">
        <div class="card">
          <div class="label">상태</div>
          <div id="statusValue" class="value">-</div>
        </div>
        <div class="card">
          <div class="label">대상 Cluster</div>
          <div id="clusterValue" class="value">-</div>
        </div>
        <div class="card">
          <div class="label">Namespace</div>
          <div id="namespaceValue" class="value">-</div>
        </div>
        <div class="card">
          <div class="label">Task Queue</div>
          <div id="queueValue" class="value">-</div>
        </div>
      </section>

      <section class="panel">
        <h2>자동 감시 보드</h2>
        <div class="watch-grid">
          <div id="opsWatchCard" class="watch-item pending">
            <div class="watch-title">Ops EKS</div>
            <div id="opsWatchStatus" class="watch-status pending-text">확인 중</div>
            <div id="opsWatchMeta" class="watch-meta">마지막 확인: -</div>
          </div>
          <div id="serviceWatchCard" class="watch-item pending">
            <div class="watch-title">Service EKS</div>
            <div id="serviceWatchStatus" class="watch-status pending-text">확인 중</div>
            <div id="serviceWatchMeta" class="watch-meta">마지막 확인: -</div>
          </div>
          <div id="autoRefreshCard" class="watch-item pending">
            <div class="watch-title">Namespace 자동 갱신</div>
            <div id="autoRefreshStatus" class="watch-status pending-text">활성</div>
            <div id="autoRefreshMeta" class="watch-meta">주기: 3초</div>
          </div>
        </div>
      </section>

      <section class="layout">
        <div class="panel">
          <h2>수동 실행</h2>
          <label>Cluster</label>
          <div id="clusterSegments" class="segmented">
            <button class="segment active" data-cluster="financial-ops-eks">financial-ops-eks</button>
            <button class="segment" data-cluster="financial-service-eks">financial-service-eks</button>
          </div>
          <label>Namespace</label>
          <div id="namespaceSegments" class="segmented namespace-grid"></div>
          <label for="workflowId">Workflow ID</label>
          <input id="workflowId" placeholder="비워두면 자동 생성" />
          <div class="actions">
            <button id="runButton">AIOps 실행</button>
            <button id="clearButton" class="secondary">결과 지우기</button>
          </div>
        </div>

        <div class="panel">
          <h2>AIOps 진행 흐름</h2>
          <div class="timeline">
            <div class="step"><span>Detect: 대상 namespace에서 이상 pod 탐지</span><span class="badge">read</span></div>
            <div class="step"><span>Analyze: 원인과 복구 전략 생성</span><span class="badge">plan</span></div>
            <div class="step"><span>HITL: Slack 승인 후 execute 진행</span><span class="badge">approval</span></div>
            <div class="step"><span>Execute: restart / HPA patch / rollback 수행</span><span class="badge">change</span></div>
            <div class="step"><span>Verify: 복구 여부 확인</span><span class="badge">check</span></div>
          </div>
        </div>
      </section>

      <section class="panel">
        <h2>실행 결과</h2>
        <div class="result-grid">
          <div class="result-card">
            <h3>Input</h3>
            <pre id="inputBox">아직 실행된 워크플로우가 없습니다.</pre>
          </div>
          <div class="result-card">
            <h3>Result</h3>
            <pre id="resultBox">아직 실행된 워크플로우가 없습니다.</pre>
          </div>
        </div>
        <div id="incidentBanner" class="incident-banner ok">
          <div>
            <div class="incident-title">장애 메트릭 알림</div>
            <div id="incidentMessage" class="incident-message ok">장애 없음</div>
          </div>
          <div id="incidentChip" class="incident-chip">normal</div>
        </div>
      </section>
    </main>
    <script>
      const temporalUrl = {json.dumps(TEMPORAL_UI_URL)};
      const statusValue = document.getElementById("statusValue");
      const clusterValue = document.getElementById("clusterValue");
      const namespaceValue = document.getElementById("namespaceValue");
      const queueValue = document.getElementById("queueValue");
      const clusterSegments = document.getElementById("clusterSegments");
      const namespaceSegments = document.getElementById("namespaceSegments");
      const workflowId = document.getElementById("workflowId");
      const inputBox = document.getElementById("inputBox");
      const resultBox = document.getElementById("resultBox");
      const incidentBanner = document.getElementById("incidentBanner");
      const incidentMessage = document.getElementById("incidentMessage");
      const incidentChip = document.getElementById("incidentChip");
      const opsWatchCard = document.getElementById("opsWatchCard");
      const opsWatchStatus = document.getElementById("opsWatchStatus");
      const opsWatchMeta = document.getElementById("opsWatchMeta");
      const serviceWatchCard = document.getElementById("serviceWatchCard");
      const serviceWatchStatus = document.getElementById("serviceWatchStatus");
      const serviceWatchMeta = document.getElementById("serviceWatchMeta");
      const autoRefreshCard = document.getElementById("autoRefreshCard");
      const autoRefreshStatus = document.getElementById("autoRefreshStatus");
      const autoRefreshMeta = document.getElementById("autoRefreshMeta");
      const runButton = document.getElementById("runButton");
      const namespaceByCluster = {{
        "financial-ops-eks": ["tetragon", "aiops-mas", "finops-mas", "secops-mas", "platform-mas"],
        "financial-service-eks": ["stock-demo"],
      }};
      const clusters = ["financial-ops-eks", "financial-service-eks"];
      let selectedCluster = "financial-ops-eks";
      let selectedNamespace = "tetragon";
      let currentWorkflowId = "";
      let currentWorkflowCluster = "";
      let namespaceRefreshMessage = "";
      const watchState = {{
        "financial-ops-eks": {{ lastCheckedAt: null, ok: false, incident: "checking", error: "", normalPodCount: 0, problemPodCount: 0, otherPodCount: 0, problemNamespaces: [] }},
        "financial-service-eks": {{ lastCheckedAt: null, ok: false, incident: "checking", error: "", normalPodCount: 0, problemPodCount: 0, otherPodCount: 0, problemNamespaces: [] }},
      }};

      function incidentTextForCluster(clusterName) {{
        return clusterName === "financial-service-eks" ? "Service EKS 장애 발생" : "Ops EKS 장애 발생";
      }}

      function formatElapsed(timestamp) {{
        if (!timestamp) return "-";
        const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
        if (seconds < 2) return "방금 전";
        return `${{seconds}}초 전`;
      }}

      function setWatchCard(card, statusElement, metaElement, state, title) {{
        const cardState = state.ok ? state.incident : "failed";
        if (cardState === "alert") {{
          card.className = "watch-item alert";
          statusElement.className = "watch-status err";
          statusElement.textContent = title === "service" ? "Service EKS 장애 발생" : "Ops EKS 장애 발생";
        }} else if (cardState === "checking") {{
          card.className = "watch-item pending";
          statusElement.className = "watch-status pending-text";
          statusElement.textContent = "확인 중";
        }} else if (cardState === "failed") {{
          card.className = "watch-item alert";
          statusElement.className = "watch-status err";
          statusElement.textContent = "확인 실패";
        }} else {{
          card.className = "watch-item ok";
          statusElement.className = "watch-status ok";
          statusElement.textContent = "정상";
        }}
        const counts = `정상 Pod ${{state.normalPodCount}}개 / 장애 Pod ${{state.problemPodCount}}개`;
        const namespaces = state.problemNamespaces.length
          ? `장애 namespace: ${{state.problemNamespaces.join(", ")}}`
          : "장애 namespace: 없음";
        const suffix = state.otherPodCount ? ` / 기타 ${{state.otherPodCount}}개` : "";
        const error = state.error ? `\n오류: ${{state.error}}` : "";
        metaElement.textContent = `${{counts}}${{suffix}}\n${{namespaces}}\n마지막 확인: ${{formatElapsed(state.lastCheckedAt)}}${{error}}`;
      }}

      function updateWatchBoard() {{
        const opsState = watchState["financial-ops-eks"];
        const serviceState = watchState["financial-service-eks"];
        setWatchCard(opsWatchCard, opsWatchStatus, opsWatchMeta, opsState, "ops");
        setWatchCard(serviceWatchCard, serviceWatchStatus, serviceWatchMeta, serviceState, "service");
        const allOk = opsState.ok && serviceState.ok;
        autoRefreshCard.className = `watch-item ${{allOk ? "ok" : "pending"}}`;
        autoRefreshStatus.className = `watch-status ${{allOk ? "ok" : "pending-text"}}`;
        autoRefreshStatus.textContent = "활성";
        autoRefreshMeta.textContent = allOk ? "주기: 3초 / 최근 갱신 성공" : "주기: 3초 / 갱신 확인 중";
      }}

      function renderIncidentState(state, clusterName = selectedCluster) {{
        incidentBanner.className = `incident-banner ${{state}}`;
        incidentMessage.className =
          `incident-message ${{state === "alert" ? "err" : state === "pending" ? "pending-text" : "ok"}}`;
        if (state === "alert") {{
          incidentMessage.textContent = incidentTextForCluster(clusterName);
          incidentChip.textContent = clusterName === "financial-service-eks" ? "service" : "ops";
          if (watchState[clusterName]) {{
            watchState[clusterName].incident = "alert";
            updateWatchBoard();
          }}
          return;
        }}
        if (state === "pending") {{
          incidentMessage.textContent = "장애 여부 확인 중";
          incidentChip.textContent = "checking";
          return;
        }}
        incidentMessage.textContent = "장애 없음";
        incidentChip.textContent = "normal";
        if (watchState[clusterName]) {{
          watchState[clusterName].incident = "normal";
          updateWatchBoard();
        }}
      }}

      function selectedTarget() {{
        return {{ cluster_name: selectedCluster, namespace: selectedNamespace }};
      }}

      function setActiveButton(container, attrName, value) {{
        [...container.querySelectorAll("button")].forEach((button) => {{
          button.classList.toggle("active", button.dataset[attrName] === value);
        }});
      }}

      function renderNamespaceSegments() {{
        const namespaces = namespaceByCluster[selectedCluster] || [];
        if (!namespaces.includes(selectedNamespace)) {{
          selectedNamespace = namespaces[0] || "";
        }}
        if (namespaces.length === 0) {{
          namespaceSegments.innerHTML = '<button class="segment" disabled>namespace 없음</button>';
          return;
        }}
        namespaceSegments.innerHTML = namespaces
          .map((namespace) => (
            `<button class="segment ${{namespace === selectedNamespace ? "active" : ""}}" ` +
            `data-namespace="${{namespace}}">${{namespace}}</button>`
          ))
          .join("");
      }}

      function syncTargetCards() {{
        const target = selectedTarget();
        clusterValue.textContent = target.cluster_name;
        namespaceValue.textContent = target.namespace;
        setActiveButton(clusterSegments, "cluster", selectedCluster);
        renderNamespaceSegments();
      }}

      function applyClusterSummary(summary) {{
        const clusterName = summary.cluster_name;
        if (!watchState[clusterName]) return;
        if (Array.isArray(summary.namespace_names)) {{
          namespaceByCluster[clusterName] = summary.namespace_names;
        }}
        watchState[clusterName].lastCheckedAt = Date.now();
        watchState[clusterName].ok = !summary.error;
        watchState[clusterName].error = summary.error || "";
        watchState[clusterName].normalPodCount = Number(summary.normal_pod_count || 0);
        watchState[clusterName].problemPodCount = Number(summary.problem_pod_count || 0);
        watchState[clusterName].otherPodCount = Number(summary.other_pod_count || 0);
        watchState[clusterName].problemNamespaces = Array.isArray(summary.problem_namespaces)
          ? summary.problem_namespaces
          : [];
        watchState[clusterName].incident = watchState[clusterName].problemPodCount > 0 ? "alert" : "normal";
      }}

      async function refreshDashboard() {{
        try {{
          const response = await fetch("/api/dashboard");
          if (!response.ok) throw new Error(await response.text());
          const data = await response.json();
          (data.cluster_summaries || []).forEach(applyClusterSummary);
          namespaceRefreshMessage = "";
          syncTargetCards();
          updateWatchBoard();
          statusValue.textContent = "ready";
          statusValue.className = "value ok";
          queueValue.textContent = data.task_queue || "-";
          if (namespaceRefreshMessage) {{
            resultBox.textContent = namespaceRefreshMessage;
          }}
        }} catch (error) {{
          clusters.forEach((clusterName) => {{
            watchState[clusterName].lastCheckedAt = Date.now();
            watchState[clusterName].ok = false;
            watchState[clusterName].error = String(error);
          }});
          updateWatchBoard();
          statusValue.textContent = "error";
          statusValue.className = "value err";
          queueValue.textContent = "-";
          resultBox.textContent = `dashboard error: ${{error}}`;
        }}
      }}

      function renderInput(data) {{
        const workflowLink = `${{temporalUrl}}/namespaces/default/workflows/${{data.workflow_id}}`;
        inputBox.innerHTML =
          `workflow_id: <a href="${{workflowLink}}" target="_blank" rel="noreferrer">${{data.workflow_id}}</a>\\n` +
          `cluster: ${{data.cluster_name}}\\n` +
          `namespace: ${{data.namespace}}\\n` +
          `task_queue: ${{data.task_queue}}`;
      }}

      function renderResult(detail) {{
        resultBox.textContent =
          `status: ${{detail.status || "-"}}\\n` +
          `result: ${{detail.result === null || detail.result === undefined ? "(아직 완료되지 않음)" : detail.result}}`;
        if (detail.result === "no_incident") {{
          renderIncidentState("ok", currentWorkflowCluster);
        }} else if (detail.result !== null && detail.result !== undefined) {{
          renderIncidentState("alert", currentWorkflowCluster);
        }} else if (detail.status === "RUNNING") {{
          renderIncidentState("alert", currentWorkflowCluster);
        }} else {{
          renderIncidentState("pending", currentWorkflowCluster);
        }}
      }}

      async function refreshWorkflowResult() {{
        if (!currentWorkflowId) return;
        const response = await fetch(`/api/workflows/${{currentWorkflowId}}`);
        if (!response.ok) throw new Error(await response.text());
        const detail = await response.json();
        renderResult(detail);
        return detail;
      }}

      async function pollWorkflowResult() {{
        for (let attempt = 0; attempt < 8; attempt += 1) {{
          const detail = await refreshWorkflowResult();
          if (detail && detail.result !== null && detail.result !== undefined) return;
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }}
      }}

      async function runWorkflow() {{
        const target = selectedTarget();
        runButton.disabled = true;
        inputBox.textContent = JSON.stringify({{ ...target, workflow_id: workflowId.value.trim() || null }}, null, 2);
        resultBox.textContent = "AIOps workflow를 시작하는 중입니다...";
        renderIncidentState("pending", target.cluster_name);
        try {{
          const body = {{
            ...target,
            workflow_id: workflowId.value.trim() || null,
          }};
          const response = await fetch("/api/workflows/run", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(body),
          }});
          if (!response.ok) throw new Error(await response.text());
          const data = await response.json();
          currentWorkflowId = data.workflow_id;
          currentWorkflowCluster = data.cluster_name;
          renderInput(data);
          resultBox.textContent = "workflow 시작됨. result 조회 중...";
          await pollWorkflowResult();
        }} catch (error) {{
          resultBox.textContent = `run error: ${{error}}`;
        }} finally {{
          runButton.disabled = false;
        }}
      }}

      clusterSegments.addEventListener("click", (event) => {{
        if (!event.target.dataset.cluster) return;
        selectedCluster = event.target.dataset.cluster;
        syncTargetCards();
      }});
      namespaceSegments.addEventListener("click", (event) => {{
        if (!event.target.dataset.namespace) return;
        selectedNamespace = event.target.dataset.namespace;
        syncTargetCards();
      }});
      document.getElementById("refreshButton").addEventListener("click", refreshDashboard);
      document.getElementById("clearButton").addEventListener("click", () => {{
        currentWorkflowId = "";
        currentWorkflowCluster = "";
        inputBox.textContent = "아직 실행된 워크플로우가 없습니다.";
        resultBox.textContent = "아직 실행된 워크플로우가 없습니다.";
        renderIncidentState("ok");
      }});
      runButton.addEventListener("click", runWorkflow);
      updateWatchBoard();
      refreshDashboard();
      setInterval(refreshDashboard, 3000);
      setInterval(updateWatchBoard, 1000);
    </script>
  </body>
</html>
"""
