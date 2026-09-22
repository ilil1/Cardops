"""신용카드 고객 이탈 예측 서비스를 제공하는 FastAPI 진입점입니다."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import APP_NAME, APP_VERSION, get_model_dir
from .config import get_cors_origins, get_database_url, get_jwt_secret
from .database import initialize_database
from .model_registry import ModelRegistry
from .api.router import api_router


def create_app(
    model_dir: Path | None = None,
    database_url: str | None = None,
    jwt_secret: str | None = None,
) -> FastAPI:
    """테스트와 운영 환경에서 모델·데이터베이스 경로를 주입할 수 있는 앱을 생성합니다."""

    configured_database_url = (
        get_database_url() if database_url is None else database_url
    )
    configured_jwt_secret = get_jwt_secret() if jwt_secret is None else jwt_secret

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        """서버 시작과 종료에 맞춰 DB와 모델의 생명주기를 관리합니다."""
        database_engine = None
        if configured_database_url:
            if not configured_jwt_secret or len(configured_jwt_secret) < 32:
                raise RuntimeError(
                    "JWT_SECRET must be configured with at least 32 characters "
                    "when DATABASE_URL is set."
                )
            database_engine, session_factory = initialize_database(
                configured_database_url,
            )
            application.state.session_factory = session_factory
            application.state.jwt_secret = configured_jwt_secret

        # 모델은 요청마다 다시 읽지 않고 서버 시작 시 한 번만 메모리에 적재합니다.
        registry = ModelRegistry(model_dir or get_model_dir())
        registry.load()
        application.state.model_registry = registry
        yield
        # 애플리케이션 종료 시 공유 상태의 참조를 해제합니다.
        application.state.model_registry = None
        application.state.session_factory = None
        application.state.jwt_secret = None
        if database_engine is not None:
            database_engine.dispose()

    application = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description=(
            "선정된 고객 이탈 분류 모델을 적재하고 고객별 이탈 여부와 "
            "이탈 확률을 예측합니다."
        ),
        lifespan=lifespan,
    )

    cors_origins = get_cors_origins()
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    application.include_router(api_router)
    return application


app = create_app()
