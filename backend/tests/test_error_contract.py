"""错误响应的契约验证：统一为 {"detail": {"code", "message"}}。"""

from __future__ import annotations


def test_health_contract(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "CVPlatform API"}


def test_malformed_json_body_is_invalid_parameter(client):
    """请求体格式错误与参数越界属于同一类问题，应使用同一错误码。"""
    response = client.post(
        "/api/papers",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_parameter"


def test_missing_required_field_reports_field_name(client):
    response = client.post("/api/papers", json={"title": "A Long Enough Title"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_parameter"
    # 出错字段可定位，便于前端提示到具体控件
    assert any(item["field"] in ("conference", "year") for item in detail["fields"])


def test_duplicate_error_carries_existing_paper(client, paper_factory):
    paper_factory("A Duplicate Target Title For Testing")
    response = client.post(
        "/api/papers",
        json={
            "title": "A Duplicate Target Title For Testing",
            "conference": "CVPR",
            "year": 2024,
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "duplicate_paper"
    assert set(detail["existing"]) == {"id", "code", "title", "conference", "year"}
    assert detail["existing"]["code"] == "CVPR-2024-0001"


def test_unknown_path_uses_unified_shape(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_method_not_allowed_uses_unified_shape(client):
    response = client.put("/api/papers")
    assert response.status_code == 405
    assert response.json()["detail"]["code"] == "method_not_allowed"


def test_empty_list_response_shape(client):
    """空数据必须是空列表与 0，而不是 null；分页字段始终存在。"""
    body = client.get("/api/papers").json()
    assert body == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 8,
        "pages": 1,
        "scope": {"conferences": [], "year_from": None, "year_to": None},
        # 阶段 8 起回显统计口径约束；普通检索时为 null
        "stats_mode": None,
    }
