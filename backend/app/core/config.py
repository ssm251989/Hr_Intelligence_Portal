import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    DOCUSIGN_INTEGRATION_KEY: str = os.getenv("DOCUSIGN_INTEGRATION_KEY", "")
    DOCUSIGN_SECRET_KEY: str = os.getenv("DOCUSIGN_SECRET_KEY", "")
    DOCUSIGN_ACCOUNT_ID: str = os.getenv("DOCUSIGN_ACCOUNT_ID", "")
    DOCUSIGN_AUTH_BASE_URL: str = os.getenv("DOCUSIGN_AUTH_BASE_URL", "https://account-d.docusign.com")
    DOCUSIGN_API_BASE_URL: str = os.getenv("DOCUSIGN_API_BASE_URL", "https://demo.docusign.net")
    DOCUSIGN_REDIRECT_URI: str = os.getenv("DOCUSIGN_REDIRECT_URI", "http://localhost:8000/auth/docusign/callback")


settings = Settings()
