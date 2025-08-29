from functools import lru_cache
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")
    github_token: str = Field(..., env="GITHUB_TOKEN") 
    monday_api_key: str = Field(..., env="MONDAY_API_KEY")
    
    webhook_secret: str = Field(..., env="WEBHOOK_SECRET")
    allowed_origins: str = Field(default="*", env="ALLOWED_ORIGINS")
    
    default_repo_url: str = Field(..., env="DEFAULT_REPO_URL")
    default_base_branch: str = Field(default="main", env="DEFAULT_BASE_BRANCH")
    
    monday_board_id: str = Field(..., env="MONDAY_BOARD_ID")
    monday_task_column_id: str = Field(..., env="MONDAY_TASK_COLUMN_ID") 
    monday_status_column_id: str = Field(..., env="MONDAY_STATUS_COLUMN_ID")
    
    debug: bool = Field(default=False, env="DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    task_timeout: int = Field(default=1800, env="TASK_TIMEOUT") 
    test_timeout: int = Field(default=300, env="TEST_TIMEOUT")  
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Retourne l'instance singleton des settings."""
    return Settings() 