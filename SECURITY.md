# Security policy

## Supported versions

The latest `main` branch is supported. Deployments should pin a released image and
lock dependencies with `uv.lock`.

## Reporting a vulnerability

Do not open a public issue for a security vulnerability. Once this repository is
published, use its GitHub **Security** tab and **Report a vulnerability** form. If
private reporting is not enabled yet, contact the repository maintainer through
their GitHub profile before sharing details. Include a reproduction, impact, and
affected version. We will acknowledge reports within five business days.

## Security controls

- Uploads are bounded before persistence and validated by extension, declared type,
and magic bytes.
- User filenames are reduced to a safe display name; object keys use generated IDs.
- Uploaded bytes are treated as data only. The service never executes them.
- PDF pages, ZIP members, decompressed DOCX size, and extracted text are bounded.
- Database and object storage credentials are supplied through environment or a
secret manager, never committed.
- Production should put authentication, authorization, TLS, rate limits, and malware
scanning in front of the API. See the threat model in `README.md`.
