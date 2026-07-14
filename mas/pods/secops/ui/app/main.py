"""
SecOps UI — 대시보드 (FinOps/AIOps UI와 동일 패턴)
==================================================
SecOps orchestrator의 HTTP API(api.py)를 프록시해 화면을 그린다.
    ORCHESTRATOR_URL/api/dashboard    → 요약 + 최근 보고서/로그
    ORCHESTRATOR_URL/api/reports      → 규제 보고서 목록
    ORCHESTRATOR_URL/api/audit-logs   → 감사 로그
    ORCHESTRATOR_URL/api/workflows/run→ 탐지 워크플로 수동 실행(발표 시연)
    ORCHESTRATOR_URL/api/workflows/{id}→ 실행 결과 조회

별도 UI pod로 배포(Teleport 접속). orchestrator와 분리.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

ORCHESTRATOR_URL = os.getenv(
    "ORCHESTRATOR_URL",
    "http://secops-orchestrator.secops-mas.svc.cluster.local:8000",
)
ORCHESTRATOR_TIMEOUT_SECONDS = int(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "60"))

app = FastAPI(title="SecOps UI", version="1.0.0")


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


# ---- orchestrator 프록시 ----
@app.get("/api/dashboard")
def dashboard() -> Any:
    return call_orchestrator("/api/dashboard")


@app.get("/api/reports")
def reports(limit: int = 50) -> Any:
    return call_orchestrator(f"/api/reports?limit={limit}")


@app.get("/api/audit-logs")
def audit_logs(limit: int = 100) -> Any:
    return call_orchestrator(f"/api/audit-logs?limit={limit}")


@app.post("/api/workflows/run")
def run_workflow(trigger_message: str = "") -> Any:
    q = f"?trigger_message={quote(trigger_message)}" if trigger_message else ""
    return call_orchestrator(f"/api/workflows/run{q}", method="POST")


@app.get("/api/workflows/{workflow_id}")
def workflow_status(workflow_id: str) -> Any:
    return call_orchestrator(f"/api/workflows/{quote(workflow_id)}")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


_INDEX_HTML = r"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SecOps MAS 대시보드</title>
<style>
  :root {
    --bg:#0f1420; --panel:#161d2e; --line:#26304a; --text:#e6ecf7; --muted:#8a97b1;
    --accent:#3b82f6; --crit:#ef4444; --high:#f97316; --med:#eab308; --low:#22c55e;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Segoe UI',Arial,sans-serif; background:var(--bg); color:var(--text); }
  header { padding:16px 22px; border-bottom:1px solid var(--line); background:var(--panel);
    display:flex; justify-content:space-between; align-items:center; }
  h1 { margin:0; font-size:20px; } h2 { margin:0 0 12px; font-size:15px; color:var(--muted); font-weight:600; }
  .wrap { padding:20px 22px; max-width:1200px; margin:0 auto; }
  .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:20px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; }
  .card .n { font-size:28px; font-weight:700; } .card .l { color:var(--muted); font-size:12px; margin-top:4px; }
  .sevbar { display:flex; gap:6px; margin-top:8px; } .sevbar span { font-size:11px; padding:2px 8px; border-radius:10px; }
  .s-critical{background:var(--crit)} .s-high{background:var(--high)} .s-medium{background:var(--med);color:#000} .s-low{background:var(--low);color:#000}
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; margin-bottom:16px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { color:var(--muted); font-weight:600; }
  .btn { background:var(--accent); color:#fff; border:0; border-radius:8px; padding:10px 16px; font-size:14px; cursor:pointer; }
  .btn:disabled { opacity:.5; cursor:not-allowed; }
  .dlbtn { background:transparent; color:var(--accent); border:1px solid var(--accent); border-radius:6px; padding:3px 8px; font-size:12px; cursor:pointer; white-space:nowrap; }
  .dlbtn:hover { background:var(--accent); color:#fff; }
  .pill { font-size:11px; padding:2px 8px; border-radius:10px; background:var(--line); }
  .reg { color:var(--accent); font-size:12px; } .muted { color:var(--muted); }
  pre { background:#0b1020; padding:10px; border-radius:8px; overflow:auto; font-size:11px; max-height:200px; }
  .run-result { margin-top:12px; padding:12px; border:1px dashed var(--line); border-radius:8px; font-size:13px; }
</style>
</head>
<body>
<header>
  <h1>🛡️ SecOps MAS 대시보드</h1>
  <div>
    <button class="btn" id="runBtn" onclick="runWorkflow()">▶ 탐지 워크플로 실행 (데모)</button>
  </div>
</header>
<div class="wrap">
  <div class="cards" id="cards"></div>
  <div id="runResult"></div>
  <div class="grid">
    <div class="panel">
      <h2>규제 위반 보고서 (최근)</h2>
      <table><thead><tr><th>시각</th><th>Severity</th><th>위반 규정</th><th>격리</th><th></th></tr></thead>
      <tbody id="reports"></tbody></table>
    </div>
    <div class="panel">
      <h2>감사 로그 (최근)</h2>
      <table><thead><tr><th>시각</th><th>이벤트</th><th>요약</th></tr></thead>
      <tbody id="audit"></tbody></table>
    </div>
  </div>
</div>
<script>
const esc = s => (s==null?"":String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const sevClass = s => "pill s-"+(s||"low");
function fmt(t){ if(!t) return ""; try{ return new Date(t).toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}); }catch(e){ return t; } }

async function load() {
  try {
    const d = await (await fetch("/api/dashboard")).json();
    const s = d.summary || {};
    const sev = s.by_severity || {};
    document.getElementById("cards").innerHTML = `
      <div class="card"><div class="n">${s.total_reports??0}</div><div class="l">규제 보고서</div></div>
      <div class="card"><div class="n">${s.isolation_applied??0}</div><div class="l">격리 적용</div></div>
      <div class="card"><div class="n">${s.total_audit_logs??0}</div><div class="l">감사 로그</div></div>
      <div class="card"><div class="l">Severity 분포</div><div class="sevbar">
        ${["critical","high","medium","low"].map(k=>`<span class="s-${k}">${k} ${sev[k]||0}</span>`).join("")}
      </div></div>`;
    window._reports = d.recent_reports || [];
    document.getElementById("reports").innerHTML = (d.recent_reports||[]).map((r,i)=>`
      <tr><td>${fmt(r.generated_at)}</td><td><span class="${sevClass(r.severity)}">${esc(r.severity)}</span></td>
      <td class="reg">${(r.violated_regulations||[]).map(esc).join("<br>")}</td>
      <td>${r.isolation_applied?"✅":"—"}</td>
      <td><button class="dlbtn" onclick="downloadReport(${i})" title="JSON 다운로드">⬇ JSON</button></td></tr>`).join("") || `<tr><td colspan=5 class=muted>보고서 없음</td></tr>`;
    document.getElementById("audit").innerHTML = (d.recent_audit_logs||[]).map(a=>`
      <tr><td>${fmt(a.occurred_at)}</td><td><span class=pill>${esc(a.event_type)}</span></td><td>${esc(a.summary)}</td></tr>`
      ).join("") || `<tr><td colspan=3 class=muted>로그 없음</td></tr>`;
  } catch(e) {
    document.getElementById("cards").innerHTML = `<div class="card" style="grid-column:1/-1;color:var(--high)">orchestrator 연결 대기 중… (${esc(e.message)})</div>`;
  }
}

function downloadReport(i) {
  const r = (window._reports || [])[i];
  if (!r) return;
  const blob = new Blob([JSON.stringify(r, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const wf = r.workflow_id || ("report-" + i);
  a.href = url; a.download = `secops-report-${wf}.json`;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function runWorkflow() {
  const btn = document.getElementById("runBtn"); btn.disabled = true; btn.textContent = "실행 중…";
  const box = document.getElementById("runResult");
  try {
    const started = await (await fetch("/api/workflows/run", {method:"POST"})).json();
    const wfId = started.workflow_id;
    box.innerHTML = `<div class="run-result">워크플로 시작: <b>${esc(wfId)}</b> — 결과 대기 중…</div>`;
    // 폴링 (최대 ~40초)
    for (let i=0;i<20;i++) {
      await new Promise(r=>setTimeout(r,2000));
      const st = await (await fetch("/api/workflows/"+encodeURIComponent(wfId))).json();
      if (st.status==="COMPLETED" && st.result) {
        const r = st.result;
        box.innerHTML = `<div class="run-result">
          <b>✅ 완료</b> — ${esc(wfId)}<br>
          Severity: <span class="${sevClass(r.severity)}">${esc(r.severity)}</span> ·
          격리: ${r.isolation_applied?"✅ 적용":"— 미적용"}<br>
          위반 규정: <span class="reg">${(r.violated_regulations||[]).map(esc).join(", ")}</span><br>
          <details><summary>증적(evidence)</summary><pre>${esc(JSON.stringify(r.evidence||{},null,2))}</pre></details>
        </div>`;
        load(); return;
      }
      if (["FAILED","TIMED_OUT","TERMINATED","CANCELED"].includes(st.status)) {
        box.innerHTML = `<div class="run-result" style="color:var(--high)">종료: ${esc(st.status)}</div>`; return;
      }
    }
    box.innerHTML += `<div class="muted" style="margin-top:6px">아직 실행 중입니다(승인 대기일 수 있음). 목록은 자동 갱신됩니다.</div>`;
    load();
  } catch(e) {
    box.innerHTML = `<div class="run-result" style="color:var(--high)">실행 실패: ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "▶ 탐지 워크플로 실행 (데모)";
  }
}

load();
setInterval(load, 15000);
</script>
</body>
</html>
"""
