from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from document_ingestion.persistence import Base


class Database:
    """Async SQLAlchemy 2 database wrapper for SQLite and PostgreSQL URLs."""

    def __init__(self, url: str, echo: bool = False) -> None:
        self.url = url
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self.engine: AsyncEngine = create_async_engine(
            url, echo=echo, connect_args=connect_args, pool_pre_ping=True
        )
        if url.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", self._enable_sqlite_foreign_keys)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async def create_all(self) -> None:
        self._ensure_sqlite_parent()
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    def _ensure_sqlite_parent(self) -> None:
        if not self.url.startswith("sqlite") or ":memory:" in self.url:
            return
        database_path = self.url.rsplit("///", 1)[-1].split("?", 1)[0]
        if database_path:
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
