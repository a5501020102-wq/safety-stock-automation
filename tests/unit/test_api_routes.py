"""API 路由的單元測試：錯誤一律以 JSON 錯誤碼回應，非預期例外不外洩細節。"""

import pytest
from app import app as flask_app

from src.api.responses import ApiError, error_boundary


@pytest.fixture
def client():
    return flask_app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_unknown_route_returns_json(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.get_json()["code"] == "NOT_FOUND"


def test_missing_sales_file_checked_before_params(client):
    resp = client.post("/api/calculate", json={"params": {"calcMode": "x"}})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "MISSING_SALES_FILE"


def test_ma_detail_requires_monthly_data(client):
    resp = client.post("/api/ma-detail", json={"monthlyData": {}})
    assert resp.get_json()["code"] == "MISSING_MONTHLY_VALUES"


class TestErrorBoundary:
    def test_unexpected_error_becomes_code_without_detail(self):
        with flask_app.app_context(), pytest.raises(ApiError) as exc_info, error_boundary("CALC_FAILED", "boom"):
            raise KeyError("secret")
        assert exc_info.value.code == "CALC_FAILED"
        assert exc_info.value.extra == {}

    def test_debug_mode_includes_detail(self):
        flask_app.config["DEBUG_ERRORS"] = True
        try:
            with flask_app.app_context(), pytest.raises(ApiError) as exc_info, error_boundary(
                "CALC_FAILED", "boom", include_traceback=True
            ):
                raise KeyError("secret")
        finally:
            flask_app.config["DEBUG_ERRORS"] = False
        assert exc_info.value.extra["detail"] == "'secret'"
        assert "Traceback" in exc_info.value.extra["traceback"]

    def test_api_error_passes_through(self):
        with flask_app.app_context(), pytest.raises(ApiError) as exc_info, error_boundary("CALC_FAILED", "boom"):
            raise ApiError("NO_RESULTS", "x")
        assert exc_info.value.code == "NO_RESULTS"
