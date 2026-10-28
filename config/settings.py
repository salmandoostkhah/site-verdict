from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    REQUEST_TIMEOUT: float = 15.0
    MAX_CONCURRENT_LINK_CHECKS: int = 15
    LINK_TIMEOUT: float = 6.0
    MAX_SITEMAP_URLS_TO_CHECK: int = 30
    MAX_CONCURRENT_SITEMAP_CHECKS: int = 8
    # TLS verification: پیش‌فرض امن. تنها در صورت نیاز محیط‌های تستی با مقدار True مقداردهی شود
    ALLOW_INSECURE_TLS: bool = False
settings = Settings()