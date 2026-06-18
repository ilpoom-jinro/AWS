"""
SDK 환경변수 단일 진입점

모든 설정은 환경변수에서 읽습니다
EKS에서는 ConfigMap/Secret을 통해 주입합니다

설정은 프로세스 시작 시 1회만 파싱하며,
설정 오류는 애플리케이션 시작 단계에서 즉시 실패합니다

EKS 배포 시 주입 예시:
    - AWS_REGION      → ConfigMap
    - DATABASE_URL   → Secret
"""

from functools import lru_cache

from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SDKSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 다른 팀 환경변수와 충돌 방지
    )

    # AWS
    # EKS IRSA 환경에서는 AWS_ROLE_ARN / AWS_WEB_IDENTITY_TOKEN_FILE 이 자동주입됩니다
    #
    # boto3 Default Credential Chain 사용
    # Access Key 직접 주입 금지!!!
    aws_region: str = "ap-northeast-2"

    # PostgreSQL (RDS)
    # 예: postgresql+asyncpg://user:pass@host:5432/dbname
    # 기본값 없음
    # 미설정 또는 형식 오류 시 ValidationError 발생
    database_url: PostgresDsn

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True

    @field_validator("database_url")
    @classmethod
    def validate_asyncpg_driver(
        cls,
        value: PostgresDsn,
    ) -> PostgresDsn:
        if value.scheme != "postgresql+asyncpg":
            raise ValueError(
                "DATABASE_URL은 "
                "'postgresql+asyncpg://user:pass@host:5432/dbname' "
                "형식이어야 합니다"
            )

        return value


@lru_cache(maxsize=1)
def get_settings() -> SDKSettings:
    """
    프로세스 내 1회만 설정을 파싱합니다

    테스트 시:

        get_settings.cache_clear()

    이후 환경변수를 변경하고 다시 호출하면 됩니다
    """

    return SDKSettings()