from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_database(owner_engine):
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": True}
