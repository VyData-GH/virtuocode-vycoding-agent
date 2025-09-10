from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }
    
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    github_token: str = Field(..., env="GITHUB_TOKEN") 
    monday_client_id: str = Field(..., env="MONDAY_CLIENT_ID")
    monday_client_key: str = Field(..., env="MONDAY_CLIENT_KEY") 
    monday_app_id: str = Field(..., env="MONDAY_APP_ID")    
    monday_api_token: str = Field(..., env="MONDAY_API_TOKEN")
    webhook_secret: str = Field(..., env="WEBHOOK_SECRET")
    allowed_origins: str = Field(default="*", env="ALLOWED_ORIGINS")    
    default_repo_url: str = Field(..., env="DEFAULT_REPO_URL")
    default_base_branch: str = Field(default="main", env="DEFAULT_BASE_BRANCH")
    git_user_name: str = Field(default="AI-Agent", env="GIT_USER_NAME")
    git_user_email: str = Field(default="ai-agent@example.com", env="GIT_USER_EMAIL")    
    monday_board_id: str = Field(..., env="MONDAY_BOARD_ID")
    monday_task_column_id: str = Field(..., env="MONDAY_TASK_COLUMN_ID") 
    monday_status_column_id: str = Field(..., env="MONDAY_STATUS_COLUMN_ID")    
    database_url: str = Field(default="postgresql://admin:password@localhost:5432/ai_agent_admin", env="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")    
    secret_key: str = Field(..., env="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")    
    default_ai_provider: str = Field(default="claude", env="DEFAULT_AI_PROVIDER")
    ai_model_temperature: float = Field(default=0.1, env="AI_MODEL_TEMPERATURE")
    ai_max_tokens: int = Field(default=4000, env="AI_MAX_TOKENS")    
    enable_smoke_tests: bool = Field(default=True, env="ENABLE_SMOKE_TESTS")
    test_coverage_threshold: int = Field(default=80, env="TEST_COVERAGE_THRESHOLD")
    max_test_retries: int = Field(default=3, env="MAX_TEST_RETRIES")    
    rabbitmq_host: str = Field(default="localhost", env="RABBITMQ_HOST")
    rabbitmq_port: int = Field(default=5672, env="RABBITMQ_PORT")
    rabbitmq_vhost: str = Field(default="ai_agent", env="RABBITMQ_VHOST")
    rabbitmq_user: str = Field(default="ai_agent_user", env="RABBITMQ_USER")
    rabbitmq_password: str = Field(default="secure_password_123", env="RABBITMQ_PASSWORD")
    rabbitmq_management_port: int = Field(default=15672, env="RABBITMQ_MANAGEMENT_PORT")
    rabbitmq_enable_management: bool = Field(default=True, env="RABBITMQ_ENABLE_MANAGEMENT")
    
    @property
    def celery_broker_url(self) -> str:
        return f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}@{self.rabbitmq_host}:{self.rabbitmq_port}/{self.rabbitmq_vhost}"
    
    @property 
    def celery_result_backend(self) -> str:
        return f"db+{self.database_url}"
    
    debug: bool = Field(default=False, env="DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")    
    task_timeout: int = Field(default=1800, env="TASK_TIMEOUT")  # 30 minutes
    test_timeout: int = Field(default=300, env="TEST_TIMEOUT")   # 5 minutes
    admin_frontend_url: str = Field(default="http://localhost:3000", env="ADMIN_FRONTEND_URL")    
    enable_metrics: bool = Field(default=True, env="ENABLE_METRICS")
    metrics_port: int = Field(default=8080, env="METRICS_PORT")


@lru_cache()
def get_settings() -> Settings:
    return Settings() 