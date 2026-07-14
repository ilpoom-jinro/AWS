"""
financial-secops-iam-responder Lambda
======================================
계정 탈취 대응 — IAM 정책 detach / AccessKey 비활성화를 실제로 실행한다.

왜 이 Lambda가 있는가: ops VPC(vpc2)는 IGW/NAT가 없는 격리망이고, IAM은
ap-northeast-2에 PrivateLink가 없어(us-east-1 전용) secops-orchestrator가 IAM을
직접 호출할 수 없다. 이 Lambda는 VpcConfig 없이(= VPC 미연결) 배포돼 AWS 관리형
네트워킹으로 IAM 글로벌 엔드포인트에 바로 닿는다 — orchestrator는
lambda:InvokeFunction으로 이 함수만 호출한다(mas/pods/secops/orchestrator/app/
activities.py의 revoke_iam_privilege 참고).

원본: mas/pods/secops/orchestrator/app/activities.py의 _revoke_iam_privilege +
_describe_iam_action을 그대로 이식(둘 다 순수 dict→str 함수라 Temporal/Pydantic
의존이 없어 옮기기 쉬웠다). orchestrator 쪽 _describe_iam_action은 1차 승인
dry-run 설명을 만들 때 여전히 필요해 남겨두고 여기서도 방어적으로 다시 검증한다
(호출자가 사전 검증했다고 무조건 신뢰하지 않음 — 이 Lambda가 IAM을 실제로
바꾸는 마지막 경계이므로).

입력(event):
    {"evidence": {...CloudTrail 증적 dict...}, "dry_run": bool}
    evidence 키: event_name, target_user, target_role, policy_arn, access_key_id
    (mas/pods/secops/orchestrator/app/detection.py의 extract_evidence와 동일 스키마)

출력: {"success": bool, "action_taken": str, "output": str | None}

지원 대상 외(PutUserPolicy 등 인라인 정책, AttachGroupPolicy, evidence 불충분)는
success=False로 반환 — 추측으로 잘못된 API를 부르지 않는다. 실제 IAM 회수 권한
(Allow user/* detach/delete/update + Deny role/*·팀원 보호)은 이 함수 실행 role
(secops-iam-responder.tf의 secops_iam_responder_lambda_iam_response)에만 있다.

현재상태 확인(list_attached_user_policies/list_attached_role_policies/
list_access_keys): 반복 lookback으로 같은 회수 대상이 여러 이벤트에 걸쳐 중복
잡히거나, 이 함수 자체가 재시도(Temporal 재시도 등)되는 경우를 대비해 실제
detach/deactivate 전에 지금도 유효한 대상인지 먼저 확인한다. 이미 detach/
비활성화/삭제된 대상은 API를 다시 부르지 않고 스킵 결과를 반환한다(존재하지
않는 정책/키에 detach/update를 호출하면 IAM이 에러를 낼 수 있음 — 그 에러를
만드는 대신 "이미 원하는 상태"임을 그대로 보고). 이 조회 권한도 같은 role의
secops_iam_responder_lambda_state_check 정책에 있다 — orchestrator는 ops VPC
격리로 IAM을 전혀 조회할 수 없어(list_access_keys도 IAM API 호출), 이 확인은
반드시 이 Lambda 안에서 해야 한다.
"""

from __future__ import annotations

import boto3

# IAM 대응이 실제로 지원하는 event_name → revoke API 종류. 아래 3종만 지원 —
# 이 Lambda의 role(secops-iam-responder.tf)에 부여된 권한(DetachUserPolicy/
# DetachRolePolicy/UpdateAccessKey)과 정확히 일치시켜, 권한 없는 API를 호출하는
# 코드 경로가 생기지 않도록 한다.
_iam_client = boto3.client("iam")  # IAM은 글로벌 서비스 — region 불필요, 콜드 스타트 간 재사용


def _describe_iam_action(evidence: dict) -> str | None:
    """실행 전 '무엇을 할지' 설명 문자열. 지원 대상이 아니면 None."""
    event_name = evidence.get("event_name", "")
    policy_arn = evidence.get("policy_arn", "")
    target_user = evidence.get("target_user", "")
    target_role = evidence.get("target_role", "")
    access_key_id = evidence.get("access_key_id", "")

    if event_name == "AttachUserPolicy" and target_user and policy_arn:
        return f"DetachUserPolicy(UserName={target_user}, PolicyArn={policy_arn})"
    if event_name == "AttachRolePolicy" and target_role and policy_arn:
        return f"DetachRolePolicy(RoleName={target_role}, PolicyArn={policy_arn})"
    if event_name == "CreateAccessKey" and target_user and access_key_id:
        return f"UpdateAccessKey(UserName={target_user}, AccessKeyId={access_key_id}, Status=Inactive)"
    return None


def _is_user_policy_still_attached(target_user: str, policy_arn: str) -> bool:
    """list_attached_user_policies로 현재 실제 attach 상태 확인. 반복 lookback으로
    같은 정책 부여 이벤트가 여러 번 잡히거나, 이미 다른 경로(수동 조치 등)로
    detach된 경우 유령 회수(불필요한 API 호출/에러)를 막는다."""
    paginator = _iam_client.get_paginator("list_attached_user_policies")
    for page in paginator.paginate(UserName=target_user):
        if any(p.get("PolicyArn") == policy_arn for p in page.get("AttachedPolicies", [])):
            return True
    return False


def _is_role_policy_still_attached(target_role: str, policy_arn: str) -> bool:
    """list_attached_role_policies 버전 — 위와 동일 이유."""
    paginator = _iam_client.get_paginator("list_attached_role_policies")
    for page in paginator.paginate(RoleName=target_role):
        if any(p.get("PolicyArn") == policy_arn for p in page.get("AttachedPolicies", [])):
            return True
    return False


def _is_access_key_active(target_user: str, access_key_id: str) -> bool:
    """list_access_keys로 현재 실제 존재 + Active 상태 확인. 이미 삭제됐거나 이미
    Inactive(예: 반복 lookback으로 같은 키가 여러 이벤트에 걸쳐 잡힌 경우, 앞선
    회수 시도로 이미 비활성화된 경우)면 회수 대상에서 제외한다."""
    paginator = _iam_client.get_paginator("list_access_keys")
    for page in paginator.paginate(UserName=target_user):
        for key in page.get("AccessKeyMetadata", []):
            if key.get("AccessKeyId") == access_key_id:
                return key.get("Status") == "Active"
    return False


def _revoke_iam_privilege(evidence: dict) -> str:
    """실제 IAM detach/deactivate 호출. 반환: 사람이 읽는 결과 설명.
    실행 전 현재 상태를 먼저 조회해, 이미 detach/비활성화된 대상(반복 lookback으로
    같은 대상이 여러 이벤트에 걸쳐 잡히거나, 이 함수 자체가 재시도되는 경우)은
    다시 호출하지 않고 스킵 처리 — 존재하지 않는 대상에 API를 불러 에러를 내는
    대신, 이미 원하는 상태임을 그대로 보고한다(success=True 취급)."""
    event_name = evidence.get("event_name", "")
    policy_arn = evidence.get("policy_arn", "")
    target_user = evidence.get("target_user", "")
    target_role = evidence.get("target_role", "")
    access_key_id = evidence.get("access_key_id", "")

    if event_name == "AttachUserPolicy" and target_user and policy_arn:
        if not _is_user_policy_still_attached(target_user, policy_arn):
            return f"이미 detach됨(스킵): UserName={target_user}, PolicyArn={policy_arn}"
        _iam_client.detach_user_policy(UserName=target_user, PolicyArn=policy_arn)
        return f"DetachUserPolicy 완료: UserName={target_user}, PolicyArn={policy_arn}"

    if event_name == "AttachRolePolicy" and target_role and policy_arn:
        if not _is_role_policy_still_attached(target_role, policy_arn):
            return f"이미 detach됨(스킵): RoleName={target_role}, PolicyArn={policy_arn}"
        _iam_client.detach_role_policy(RoleName=target_role, PolicyArn=policy_arn)
        return f"DetachRolePolicy 완료: RoleName={target_role}, PolicyArn={policy_arn}"

    if event_name == "CreateAccessKey" and target_user and access_key_id:
        if not _is_access_key_active(target_user, access_key_id):
            return f"이미 비활성/삭제됨(스킵): UserName={target_user}, AccessKeyId={access_key_id}"
        _iam_client.update_access_key(UserName=target_user, AccessKeyId=access_key_id, Status="Inactive")
        return f"AccessKey 비활성화 완료: UserName={target_user}, AccessKeyId={access_key_id}"

    raise ValueError(
        f"IAM 대응 미지원 또는 evidence 불충분: event_name={event_name}, "
        f"target_user={target_user}, target_role={target_role}, "
        f"policy_arn={policy_arn}, access_key_id={access_key_id}"
    )


def lambda_handler(event: dict, _context) -> dict:
    evidence = event.get("evidence") or {}
    dry_run = bool(event.get("dry_run", False))

    description = _describe_iam_action(evidence)
    if description is None:
        return {
            "success": False,
            "action_taken": (
                f"IAM 대응 미지원 또는 정보 부족 (event_name={evidence.get('event_name', '')}) "
                f"— 자동 조치 없음, 수동 확인 필요"
            ),
            "output": None,
        }

    if dry_run:
        return {
            "success": True,
            "action_taken": f"[DRY-RUN] {description} — 실제 미적용",
            "output": description,
        }

    try:
        outcome = _revoke_iam_privilege(evidence)
    except ValueError as exc:
        return {"success": False, "action_taken": str(exc), "output": None}

    return {"success": True, "action_taken": outcome, "output": description}
