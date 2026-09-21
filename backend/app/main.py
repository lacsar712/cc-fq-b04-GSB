from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.database import Base, engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # 兼容旧库：create_all 不会给已存在的 jobs 表补列，幂等补齐（仅 Postgres 支持该语法）
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"
            )
    yield


app = FastAPI(title="FASTQ QC Pipeline Console", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
