FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock* README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations

USER nobody
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "document_ingestion.main:app", "--host", "0.0.0.0", "--port", "8000"]
