"""
하위 호환 re-export — 직접 이 파일을 수정하지 말 것.

소유별 파일:
    activities_platform.py  ← Platform Core 소유 (execute_remediation, execute_rollback, record_audit_log)
    activities_aiops.py     ← AIOps 팀 소유 (detect_incident, analyze_root_cause, verify_recovery)
"""

from .activities_aiops import analyze_root_cause, detect_incident, verify_recovery
from activities.platform import execute_remediation, execute_rollback, record_audit_log

__all__ = [
    "detect_incident",
    "analyze_root_cause",
    "execute_remediation",
    "execute_rollback",
    "verify_recovery",
    "record_audit_log",
]
