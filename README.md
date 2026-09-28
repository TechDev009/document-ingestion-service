# Document Ingestion Service

A secure, asynchronous FastAPI service for accepting PDF, TXT, Markdown, and DOCX
documents, extracting text, and persisting deterministic chunks. This is the third
independent repository in the workspace and has its own Git history.

## Quick start (local, no cloud credentials)

Python 3.12+ (3.13 is used in CI) and [uv](https://docs.astral.sh/uv/) are required.

```sh
cp .env.example .env
uv sync --locked
uv run uvicorn document_ingestion.main:app --reload
```

The default SQLite database and object files are created under `data/`. The API is
available at <http://localhost:8000>; interactive OpenAPI documentation is at
`/docs`.

```sh
curl http://localhost:8000/v1/health/live
curl http://localhost:8000/v1/health/ready
curl -F 'file=@README.md;type=text/markdown' http://localhost:8000/v1/documents
```

The upload response contains a document ID and a job ID. Poll the job until its
status is `ready`, then fetch the document to see its chunks:

```sh
curl http://localhost:8000/v1/jobs/JOB_ID
curl http://localhost:8000/v1/documents/DOCUMENT_ID
curl -X DELETE http://localhost:8000/v1/documents/DOCUMENT_ID
```

## Architecture

- `src/document_ingestion/main.py` exposes the HTTP API and health probes.
- `services.py` is the application layer. It validates uploads, coordinates storage
  and SQLAlchemy repositories, and owns idempotent processing transitions.
- `persistence.py`, `database.py`, and `repositories.py` provide typed SQLAlchemy 2
  persistence for documents, jobs, and chunks.
- `adapters/storage.py` defines an object-storage port with a safe atomic local
  filesystem adapter and a production S3 adapter.
- `adapters/queue.py` defines a local background runner and a durable RabbitMQ
  adapter. The local runner is intentionally development-only; job state remains in
  the database so re-enqueueing is safe.
- `extractors.py` uses PyMuPDF, UTF-8 decoding, markdown-it-py, and python-docx.
  `chunking.py` normalizes text and performs deterministic character/word-boundary
  chunking with overlap.
- Alembic migrations live in `migrations/` and are the production schema source of
  truth.

### Statuses and idempotency

Documents and jobs use `created`, `uploaded`, `processing`, `ready`, and `failed`.
An upload is created, stored, and moved to `uploaded` before a job is enqueued.
Processing claims the job, increments attempts, verifies the stored SHA-256 digest,
extracts and chunks text, replaces chunks in one transaction, and marks both records
`ready`. Transient failures return to `uploaded` until `MAX_RETRIES`; terminal
failures become `failed`. Reprocessing a ready job is a no-op, and repeated content
uploads resolve to the existing SHA-256 document/job rather than creating duplicate
work.

## API

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/v1/health/live` | process liveness |
| `GET` | `/v1/health/ready` | database and storage readiness |
| `POST` | `/v1/documents` | multipart field `file`; returns `202` and document/job |
| `GET` | `/v1/documents/{id}` | metadata and persisted chunks |
| `DELETE` | `/v1/documents/{id}` | removes metadata, chunks, and stored object |
| `GET` | `/v1/jobs/{id}` | processing status, attempts, and safe error |

Uploads are bounded by `MAX_UPLOAD_BYTES`, and errors identify the violated policy.
The `Idempotency-Key` header is accepted for client compatibility; content SHA-256
is the replay identity in this version.

## Worker and production deployment

For a production-like local stack with PostgreSQL, RabbitMQ, and MinIO:

```sh
uv lock
docker compose up --build
```

The Compose API runs `alembic upgrade head` before serving. The worker runs the
`document-worker` entry point and consumes durable, persistent RabbitMQ messages.
For a standalone worker process, run:

```sh
uv run document-worker
```
Replace the example credentials, put secrets in a secret manager, use real S3 and
TLS, and scale API and worker processes independently. In production set
`AUTO_CREATE_SCHEMA=false`; only the deployment migration step may change schema.
For managed S3, omit `S3_ENDPOINT_URL` and supply credentials through the workload
identity mechanism rather than environment variables where possible.

Important configuration includes:

- `DATABASE_URL`: `sqlite+aiosqlite:///...` locally or
  `postgresql+psycopg://user:password@host/db` in production.
- `STORAGE_BACKEND=local|s3`, `STORAGE_PATH`, and S3 bucket/region/endpoint fields.
- `QUEUE_BACKEND=local|rabbitmq`, `RABBITMQ_URL`, and `RABBITMQ_QUEUE`.
- `MAX_UPLOAD_BYTES`, `MAX_PDF_PAGES`, `MAX_UNCOMPRESSED_BYTES`,
  `MAX_TEXT_CHARS`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, and `MAX_RETRIES`.

## Security and threat model

The service treats every upload as hostile data. It never executes an upload or
loads macros/embedded files. It validates extension, declared MIME type, magic bytes,
UTF-8 text, and DOCX ZIP structure before persistence. Object keys use generated IDs
rather than user paths, and local storage rejects path traversal. Upload size, PDF
page count, extracted text, ZIP member count, total uncompressed DOCX size, and
compression ratio are bounded. SHA-256 detects storage corruption and makes retries
idempotent. Writes use an atomic temporary file replacement locally.

Threats that require deployment controls are authentication/authorization, tenant
isolation, denial-of-service rate limiting, malware/virus scanning, TLS termination,
secret management, audit retention, and malicious parser vulnerabilities. Put the
API behind an authenticated gateway and consider a separate sandbox/scanner before
processing untrusted files. Error messages intentionally do not expose object paths
or parser internals.

## Development and tests

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pip-audit
```

Unit and API tests use temporary SQLite and local filesystem storage; they do not
need Docker, cloud credentials, PostgreSQL, RabbitMQ, or MinIO. The optional
`testcontainers` dependency is documented for an integration suite, but
this repository's deterministic test suite deliberately does not require a running
container. Run `alembic upgrade head` to exercise the migration against the selected
`DATABASE_URL`.

## Limitations

Only text extraction is implemented; OCR for scanned PDFs is not. PDF JavaScript and
attachments are not evaluated, but a separate malware scanner is still required.
The local queue is not durable across process loss; use RabbitMQ (or replace the
queue port with a managed durable queue) for production. There is no built-in user
authentication, authorization, quota, tenant partitioning, or virus scanner.

## License

MIT; see `LICENSE`.

## Public release / status

- **Local quickstart:** Copy `.env.example`, run `uv sync --locked`, and start Uvicorn as shown in [Quick start (local, no cloud credentials)](#quick-start-local-no-cloud-credentials).
- **CI/tests:** GitHub Actions runs pytest, Ruff lint and formatting checks, Pyright, and `pip-audit`; local tests use temporary SQLite and filesystem storage without cloud credentials.
- **Limitations:** OCR, built-in authentication/authorization, quotas, tenant partitioning, and a virus scanner are not included; the local queue is not durable across process loss. See [Limitations](#limitations).
- **Production:** Real production deployment requires operator-managed credentials, TLS and security controls, durable infrastructure, and cloud/deployment infrastructure; the repository provides local and production-like building blocks, not a hosted service.
