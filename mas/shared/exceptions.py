"""
SDK 전용 예외 계층

원칙:
    - SDK 내부 구현 세부사항을 상위 레이어에 노출하지 않습니다
    - 원인 예외 정보를 유지하여 디버깅에 활용할 수 있도록 합니다
    - Retry 여부는 Workflow/Temporal 레이어에서 결정합니다

예시:

    try:
        client = get_bedrock_client()

    except BedrockClientError as e:
        raise ApplicationError(str(e)) from e

계층 구조:

    SDKError
    ├── ConfigurationError
    ├── BedrockClientError
    └── AuditLogError
"""


class SDKError(Exception):
    """
    SDK 전용 기본 예외

    모든 SDK 예외는 이 클래스를 상속한다
    """

    pass


class ConfigurationError(SDKError):
    """
    SDK 설정 관련 예외

    발생 예시:
        - 필수 환경변수 누락
        - 잘못된 설정값
        - 지원하지 않는 설정 조합
        - 초기화 구성 오류

    예:
        DATABASE_URL 형식 오류
        AWS Region 설정 오류
    """

    pass


class BedrockClientError(SDKError):
    """
    Amazon Bedrock 클라이언트 생성 또는 호출 관련 예외

    발생 예시:
        - IRSA Credential 획득 실패
        - AWS 인증 실패
        - Region 설정 오류
        - boto3 Client 생성 실패
        - Bedrock Runtime 호출 실패

    참고:
        Retry 가능 여부는 상황에 따라 다르므로...
        Workflow 레이어에서 판단합니다
    """

    pass


class AuditLogError(SDKError):
    """
    감사 로그(Audit Log) 저장 과정에서 발생한 예외

    발생 예시:
        - Database 연결 실패
        - SQLAlchemy Engine 초기화 실패
        - Session 생성 실패
        - Transaction Commit 실패
        - INSERT 실패

    AuditLog 저장 실패 시 원인 예외를 유지하여
    raise AuditLogError(...) from e 형태로 사용합니다
    """

    pass