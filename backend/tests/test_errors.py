def test_unknown_route_error_shape(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "detail" not in body
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "Not Found"
    assert body["error"]["request_id"]


def test_unhandled_exception_returns_envelope(client):
    @client.app.get("/__test_raise")
    def _raise():
        raise RuntimeError("boom")

    response = client.get("/__test_raise")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."
    assert body["error"]["request_id"]
    assert response.headers.get("X-Request-ID") == body["error"]["request_id"]
    assert "boom" not in response.text
    assert "RuntimeError" not in response.text


def test_request_id_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "manual-check-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "manual-check-123"


def test_request_id_generated(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")
