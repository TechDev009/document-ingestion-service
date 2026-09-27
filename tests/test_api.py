from fastapi.testclient import TestClient


def test_health_upload_job_flow_and_delete(client: TestClient) -> None:
    live = client.get("/v1/health/live")
    ready = client.get("/v1/health/ready")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200

    response = client.post(
        "/v1/documents",
        files={"file": ("../safe.txt", b"hello API upload", "text/plain")},
    )
    assert response.status_code == 202
    payload = response.json()
    document_id = payload["document"]["id"]
    job_id = payload["job"]["id"]
    job = client.get(f"/v1/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["status"] == "ready"
    document = client.get(f"/v1/documents/{document_id}")
    assert document.status_code == 200
    assert document.json()["status"] == "ready"
    assert document.json()["chunks"]

    duplicate = client.post(
        "/v1/documents", files={"file": ("different.txt", b"hello API upload", "text/plain")}
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["document"]["id"] == document_id

    deleted = client.delete(f"/v1/documents/{document_id}")
    assert deleted.status_code == 204
    assert client.get(f"/v1/documents/{document_id}").status_code == 404
    assert client.get(f"/v1/jobs/{job_id}").status_code == 404


def test_api_rejects_malformed_and_oversized_input(client, settings) -> None:
    malformed = client.post(
        "/v1/documents", files={"file": ("bad.pdf", b"not PDF", "application/pdf")}
    )
    assert malformed.status_code == 400
    assert "magic" in malformed.json()["detail"]

    settings.max_upload_bytes = 3
    oversized = client.post(
        "/v1/documents", files={"file": ("large.txt", b"more than three", "text/plain")}
    )
    assert oversized.status_code == 413
