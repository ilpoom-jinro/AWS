"""
Platform Core 소유 Activities — execute_remediation, execute_rollback, record_audit_log

AIOps Workflow에서 호출하지만 실행 권한은 Platform Core만 보유한다.
단, 빠른 개발을 위해 수정이 필요하다면 모든 Agent팀에서 수정해도 됩니다.

strategy_detail 인코딩 규칙 (AIOps가 생성, Platform Core가 파싱):
    scale_out : "[SCALE_OUT via HPA] action=patch_hpa target_hpa=<name>
                 namespace=<ns> maxReplicas+=<N> | <근거>"
    restart   : "[RESTART] pod=<pod_name> namespace=<ns> | <근거>"
    rollback  : "[ROLLBACK] pod=<pod_name> namespace=<ns> | <근거>"
    manual    : 자유 텍스트 (Workflow에서 이 Activity를 호출하지 않음)

공통 파싱 규칙:
    파이프(|) 앞: 실행 파라미터 (키=값, 공백 구분)
    파이프(|) 뒤: LLM 생성 근거 텍스트 (실행에 무관, 로그에만 남김)

restart / rollback의 Deployment 추론 흐름:
    1. strategy_detail의 pod= 파라미터에서 pod_name 추출
       (없으면 RemediationPlan.pod_name 폴백 — IncidentContext에서 AIOps가 채워야 함)
    2. kubectl: pod → ownerRef(ReplicaSet) → ownerRef(Deployment) 추론
    → deployment= 파라미터를 AIOps에 요구하지 않음 (요청서 §2 요건 준수)

scale_out rollback 원복 흐름:
    1. execute_remediation: HPA 패치 전 maxReplicas를 ExecutionResult.output에 저장
    2. AIOps Workflow: exec_result.output을 읽어 RemediationPlan.previous_hpa_max_replicas에 설정
    3. execute_rollback: previous_hpa_max_replicas > 0이면 그 값으로 복원
       (외부 변경이 있어도 원래 값으로 정확히 원복)
"""

from __future__ import annotations

import json
import os
import re
import subprocess

from temporalio import activity
from temporalio.exceptions import ApplicationError

from contracts.models import AuditLog, ExecutionResult, RemediationPlan
from shared.audit.repository import save_audit_log


# ---
# 내부 유틸 — strategy_detail 파싱
# ---

def _parse_kv(token_str: str) -> dict[str, str]:
    """'key=value key2=value2 ...' 문자열을 dict로 변환."""
    result: dict[str, str] = {}
    for token in token_str.split():
        if "=" in token:
            k, _, v = token.partition("=")
            result[k.strip()] = v.strip()
    return result


def _parse_strategy_detail(strategy_detail: str) -> tuple[str, dict[str, str], str]:
    """
    strategy_detail을 (tag, params, reason) 으로 분리.

    tag    : "[SCALE_OUT via HPA]" / "[RESTART]" / "[ROLLBACK]" 등 대괄호 태그
    params : 파이프 앞 키=값 파싱 결과
    reason : 파이프 뒤 근거 텍스트
    """
    tag_match = re.match(r"^\[([^\]]+)\]", strategy_detail)
    tag = tag_match.group(0) if tag_match else ""
    remainder = strategy_detail[len(tag):].strip()

    if "|" in remainder:
        param_str, _, reason = remainder.partition("|")
    else:
        param_str, reason = remainder, ""

    return tag, _parse_kv(param_str), reason.strip()


def _run_kubectl(*args: str, context: str = "") -> str:
    """
    kubectl을 실행하고 stdout을 반환. 실패 시 ApplicationError(non_retryable) 발생.

    kubectl 오류(잘못된 리소스명, 권한 없음 등)는 재시도로 고쳐지지 않으므로
    non_retryable=True로 즉시 실패시킨다.
    """
    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(args)
    env = None
    if not context:
        env = os.environ.copy()
        env.pop("KUBECONFIG", None)

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise ApplicationError(
            f"kubectl 오류: {' '.join(cmd)}\n{result.stderr.strip()}",
            non_retryable=True,
        )
    return result.stdout.strip()


def _infer_deployment_from_pod(pod_name: str, namespace: str, context: str = "") -> str:
    """
    pod_name → ReplicaSet → Deployment 이름을 kubectl로 추론한다.

    요청서 §2: "rollback 대상은 pod_name에서 Deployment를 추론합니다"
    지원 소유자 체계: Pod → ReplicaSet → Deployment (일반적인 Deployment 패턴)
    비지원 체계: StatefulSet, DaemonSet 등은 ApplicationError(non_retryable) 발생
    """
    owner_kind = _run_kubectl(
        "get", "pod", pod_name, "-n", namespace,
        "-o", "jsonpath={.metadata.ownerReferences[0].kind}",
        context=context,
    )
    owner_name = _run_kubectl(
        "get", "pod", pod_name, "-n", namespace,
        "-o", "jsonpath={.metadata.ownerReferences[0].name}",
        context=context,
    )

    if not owner_kind or not owner_name:
        raise ApplicationError(
            f"pod {pod_name}에서 ownerReference를 찾을 수 없음 — "
            "직접 생성된 pod이거나 소유자 정보가 없습니다",
            non_retryable=True,
        )

    if owner_kind == "ReplicaSet":
        deployment = _run_kubectl(
            "get", "rs", owner_name, "-n", namespace,
            "-o", "jsonpath={.metadata.ownerReferences[0].name}",
            context=context,
        )
        if not deployment:
            raise ApplicationError(
                f"ReplicaSet {owner_name}에서 Deployment를 찾을 수 없음 — "
                "독립 ReplicaSet일 수 있습니다",
                non_retryable=True,
            )
        return deployment

    elif owner_kind == "Deployment":
        return owner_name

    else:
        raise ApplicationError(
            f"pod {pod_name}의 소유자가 {owner_kind}입니다 — "
            "Deployment/ReplicaSet 소유 pod만 지원합니다 (StatefulSet/DaemonSet 등 미지원)",
            non_retryable=True,
        )


def _resolve_pod_name(params: dict[str, str], plan: RemediationPlan) -> str:
    """
    strategy_detail의 pod= 파라미터를 우선 사용하고,
    없으면 RemediationPlan.pod_name 폴백.
    """
    pod_name = params.get("pod", "") or plan.pod_name
    if not pod_name:
        raise ApplicationError(
            "pod_name을 찾을 수 없습니다. "
            "strategy_detail에 pod=<name> 을 추가하거나 "
            "AIOps Workflow에서 RemediationPlan.pod_name을 IncidentContext.pod_name으로 채워야 합니다.",
            non_retryable=True,
        )
    return pod_name


def _resolve_kube_context(params: dict[str, str], plan: RemediationPlan) -> str:
    """실행 대상 kube context를 결정한다.

    우선순위:
      1. strategy_detail의 context=<name> 또는 kube_context=<name>
      2. RemediationPlan.kube_context
      3. 빈 문자열(기존 동작: kubectl 기본 context)
    """
    return (
        params.get("context", "")
        or params.get("kube_context", "")
        or plan.kube_context
    )


# ---
# Platform Core 소유 Activities
# ---

@activity.defn(name="execute_remediation")
async def execute_remediation(plan: RemediationPlan) -> ExecutionResult:
    """
    승인된 복구 방안을 실제 클러스터에 적용한다.

    strategy별 동작:
        restart   → pod_name → Deployment 추론 → kubectl rollout restart deployment/<name>
        scale_out → kubectl patch hpa <name> --type=merge maxReplicas += N
                    (kubectl scale 금지 — HPA가 되돌림)
                    ExecutionResult.output = str(패치 전 maxReplicas)  ← rollback 원복용
        rollback  → pod_name → Deployment 추론 → kubectl rollout undo deployment/<name>
        manual    → Workflow에서 이 Activity를 호출하면 안 됨 (contracts 규칙)

    상태 변경 Activity: heartbeat 호출.
    """
    activity.heartbeat("execute_remediation 시작")

    tag, params, reason = _parse_strategy_detail(plan.strategy_detail)
    activity.logger.info(
        "execute_remediation strategy=%s tag=%s params=%s reason=%s",
        plan.strategy, tag, params, reason,
    )

    try:
        if plan.strategy == "restart":
            context = _resolve_kube_context(params, plan)
            namespace = params.get("namespace", "default")
            pod_name = _resolve_pod_name(params, plan)

            activity.heartbeat(f"pod {pod_name}에서 Deployment 추론 중")
            deployment = _infer_deployment_from_pod(pod_name, namespace, context)

            activity.heartbeat(f"deployment/{deployment} 재시작 중")
            _run_kubectl("rollout", "restart",
                         f"deployment/{deployment}", "-n", namespace,
                         context=context)
            return ExecutionResult(
                workflow_id=plan.workflow_id,
                success=True,
                action_taken=(
                    f"kubectl"
                    f"{f' --context {context}' if context else ''} "
                    f"rollout restart deployment/{deployment} -n {namespace}"
                ),
                output=deployment,
            )

        elif plan.strategy == "scale_out":
            context = _resolve_kube_context(params, plan)
            target_hpa = params.get("target_hpa", "")
            namespace = params.get("namespace", "default")
            delta_str = params.get("maxReplicas+", "")
            if not target_hpa or not delta_str:
                raise ApplicationError(
                    "strategy_detail에 target_hpa= 또는 maxReplicas+=<N> 파라미터 없음",
                    non_retryable=True,
                )
            delta = int(delta_str)

            activity.heartbeat("현재 maxReplicas 조회 중")
            current_raw = _run_kubectl(
                "get", "hpa", target_hpa, "-n", namespace,
                "-o", "jsonpath={.spec.maxReplicas}",
                context=context,
            )
            previous_max = int(current_raw)
            new_max = previous_max + delta

            activity.heartbeat(f"HPA patch: maxReplicas {previous_max} → {new_max}")
            patch = json.dumps({"spec": {"maxReplicas": new_max}})
            _run_kubectl(
                "patch", "hpa", target_hpa, "-n", namespace,
                "--type=merge", "-p", patch,
                context=context,
            )
            return ExecutionResult(
                workflow_id=plan.workflow_id,
                success=True,
                action_taken=(
                    f"kubectl"
                    f"{f' --context {context}' if context else ''} "
                    f"patch hpa {target_hpa} -n {namespace} "
                    f"maxReplicas {previous_max}→{new_max}"
                ),
                output=str(previous_max),
            )

        elif plan.strategy == "rollback":
            context = _resolve_kube_context(params, plan)
            namespace = params.get("namespace", "default")
            pod_name = _resolve_pod_name(params, plan)

            activity.heartbeat(f"pod {pod_name}에서 Deployment 추론 중")
            deployment = _infer_deployment_from_pod(pod_name, namespace, context)

            activity.heartbeat(f"rollout undo deployment/{deployment}")
            _run_kubectl("rollout", "undo",
                         f"deployment/{deployment}", "-n", namespace,
                         context=context)
            return ExecutionResult(
                workflow_id=plan.workflow_id,
                success=True,
                action_taken=(
                    f"kubectl"
                    f"{f' --context {context}' if context else ''} "
                    f"rollout undo deployment/{deployment} -n {namespace}"
                ),
                output=deployment,
            )

        else:  # manual
            raise ApplicationError(
                "strategy=manual인 경우 execute_remediation을 호출하면 안 됩니다 "
                "(contracts/activity_interfaces.py 주의 참고)",
                non_retryable=True,
            )

    except ApplicationError:
        raise
    except Exception as exc:
        raise RuntimeError(f"execute_remediation 실패: {exc}") from exc


@activity.defn(name="execute_rollback")
async def execute_rollback(plan: RemediationPlan) -> ExecutionResult:
    """
    verify_recovery 실패 시 직전 조치를 되돌린다.

    ── scale_out ──────────────────────────────────────────────────────────────
    plan.previous_hpa_max_replicas > 0이면 그 값으로 정확히 복원한다.
    (AIOps Workflow 책임: execute_remediation의 ExecutionResult.output 값을
     RemediationPlan.previous_hpa_max_replicas에 저장한 뒤 이 Activity 호출)

    previous_hpa_max_replicas == 0(미설정)이면 current - delta로 폴백하며 경고를 남긴다.
    이 경우 외부 변경이 개입했다면 원복이 부정확할 수 있다.

    ── restart / rollback ─────────────────────────────────────────────────────
    pod_name → Deployment 추론 → kubectl rollout undo
    (deployment= 파라미터 요구 없음 — 요청서 §2 준수)
    """
    activity.heartbeat("execute_rollback 시작")

    tag, params, reason = _parse_strategy_detail(plan.strategy_detail)
    activity.logger.info(
        "execute_rollback strategy=%s tag=%s params=%s",
        plan.strategy, tag, params,
    )

    try:
        if plan.strategy == "scale_out":
            context = _resolve_kube_context(params, plan)
            target_hpa = params.get("target_hpa", "")
            namespace = params.get("namespace", "default")
            delta_str = params.get("maxReplicas+", "")
            if not target_hpa:
                raise ApplicationError(
                    "execute_rollback(scale_out): strategy_detail에 target_hpa= 없음",
                    non_retryable=True,
                )

            activity.heartbeat("현재 maxReplicas 조회 중")
            current_raw = _run_kubectl(
                "get", "hpa", target_hpa, "-n", namespace,
                "-o", "jsonpath={.spec.maxReplicas}",
                context=context,
            )

            if plan.previous_hpa_max_replicas > 0:
                restore_max = plan.previous_hpa_max_replicas
                activity.logger.info(
                    "HPA rollback(exact): %s → %s (previous_hpa_max_replicas)",
                    current_raw, restore_max,
                )
            else:
                if not delta_str:
                    raise ApplicationError(
                        "execute_rollback(scale_out): previous_hpa_max_replicas 미설정이고 "
                        "strategy_detail에 maxReplicas+=<N>도 없음 — 원복 불가",
                        non_retryable=True,
                    )
                restore_max = max(1, int(current_raw) - int(delta_str))
                activity.logger.warning(
                    "HPA rollback(fallback, delta 차감): %s → %s. "
                    "AIOps Workflow에서 RemediationPlan.previous_hpa_max_replicas를 설정하면 "
                    "외부 변경이 있어도 정확히 원복됩니다.",
                    current_raw, restore_max,
                )

            activity.heartbeat(f"HPA rollback: maxReplicas {current_raw} → {restore_max}")
            patch = json.dumps({"spec": {"maxReplicas": restore_max}})
            _run_kubectl(
                "patch", "hpa", target_hpa, "-n", namespace,
                "--type=merge", "-p", patch,
                context=context,
            )
            return ExecutionResult(
                workflow_id=plan.workflow_id,
                success=True,
                action_taken=(
                    f"rollback: kubectl"
                    f"{f' --context {context}' if context else ''} "
                    f"patch hpa {target_hpa} -n {namespace} "
                    f"maxReplicas {current_raw}→{restore_max}"
                ),
            )

        else:
            context = _resolve_kube_context(params, plan)
            namespace = params.get("namespace", "default")
            pod_name = _resolve_pod_name(params, plan)

            activity.heartbeat(f"pod {pod_name}에서 Deployment 추론 중")
            deployment = _infer_deployment_from_pod(pod_name, namespace, context)

            activity.heartbeat(f"rollout undo deployment/{deployment}")
            _run_kubectl("rollout", "undo",
                         f"deployment/{deployment}", "-n", namespace,
                         context=context)
            return ExecutionResult(
                workflow_id=plan.workflow_id,
                success=True,
                action_taken=(
                    f"rollback: kubectl"
                    f"{f' --context {context}' if context else ''} "
                    f"rollout undo "
                    f"deployment/{deployment} -n {namespace}"
                ),
            )

    except ApplicationError:
        raise
    except Exception as exc:
        raise RuntimeError(f"execute_rollback 실패: {exc}") from exc


@activity.defn(name="record_audit_log")
async def record_audit_log(log: AuditLog) -> None:
    """
    RDS PostgreSQL에 감사 로그 저장 (shared/audit/repository.py::save_audit_log).
    DATABASE_URL 환경변수 필수 (postgresql+asyncpg://user:pass@host:5432/dbname).
    """
    await save_audit_log(log)
    activity.logger.info(
        "[audit] saved workflow_id=%s event_type=%s",
        log.workflow_id, log.event_type,
    )
