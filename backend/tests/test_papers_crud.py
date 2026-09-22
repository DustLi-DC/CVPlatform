"""CRUD、去重、编号规则与关联清理的验证。"""

from __future__ import annotations

from app.config import KEYWORD_RULESET_VERSION
from app.services.papers import build_dedup_key, normalize_title

from .helpers import add_system_keyword, count_rows, set_meta


def test_create_returns_expected_contract(client, paper_factory):
    paper = paper_factory(
        "Segment Anything",
        conference="ICCV",
        year=2023,
        source_keywords=["语义分割", "目标检测"],
    )

    assert paper["code"] == "ICCV-2023-0001"
    assert paper["code_scope_mismatch"] is False
    assert paper["code_note"] is None
    assert paper["display_status"] == "review"
    assert paper["abstract_status"] == "present"
    assert paper["keyword_status"] == "pending"
    # 作者关键词单独入库，来源标注为 author
    assert {item["origin"] for item in paper["keywords"]} == {"author"}
    assert sorted(item["name"] for item in paper["keywords"]) == ["目标检测", "语义分割"]
    # 系统关键词尚未抽取，不能凭空出现
    assert paper["system_keywords"] == []


def test_detail_roundtrip(client, paper_factory):
    title = "Depth Anything: Unleashing the Power of Large-Scale Unlabeled Data"
    created = paper_factory(title)

    detail = client.get(f"/api/papers/{created['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == created["id"]
    assert body["title"] == title
    assert body["abstract"] == "一段用于测试的摘要文本。"


def test_detail_missing_returns_404(client):
    response = client.get("/api/papers/999999")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "paper_not_found"


def test_duplicate_title_same_conference_year_is_rejected(client, paper_factory):
    paper_factory("Masked Autoencoders Are Scalable Vision Learners")

    # 只有大小写、空格与标点不同，去重键应当一致
    response = client.post(
        "/api/papers",
        json={
            "title": "masked   autoencoders are scalable vision learners.",
            "conference": "CVPR",
            "year": 2024,
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "duplicate_paper"
    assert detail["existing"]["code"] == "CVPR-2024-0001"


def test_same_title_in_different_conference_year_is_allowed(client, paper_factory):
    first = paper_factory(
        "A Study of Something Specific", conference="CVPR", year=2024
    )
    second = paper_factory(
        "A Study of Something Specific", conference="ICCV", year=2023
    )
    assert first["id"] != second["id"]
    assert first["code"] == "CVPR-2024-0001"
    assert second["code"] == "ICCV-2023-0001"


def test_repeated_save_is_idempotent(client, paper_factory):
    created = paper_factory(
        "CoTracker: It is Better to Track Together",
        conference="ECCV",
        year=2024,
        source_keywords=["视频理解"],
    )
    payload = {
        "title": "CoTracker: It is Better to Track Together",
        "conference": "ECCV",
        "year": 2024,
        "source_keywords": ["视频理解"],
    }
    # 再次提交视为重复：返回冲突、整体回滚，不静默合并也不补写关联
    for _ in range(2):
        assert client.post("/api/papers", json=payload).status_code == 409

    assert client.get("/api/papers").json()["total"] == 1
    detail = client.get(f"/api/papers/{created['id']}").json()
    assert len([item for item in detail["keywords"] if item["name"] == "视频理解"]) == 1


def test_title_too_short_is_rejected(client):
    response = client.post(
        "/api/papers", json={"title": "短题目", "conference": "CVPR", "year": 2024}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_parameter"
    assert "过短" in response.json()["detail"]["message"]


def test_empty_title_is_rejected(client):
    response = client.post(
        "/api/papers", json={"title": "   ", "conference": "CVPR", "year": 2024}
    )
    assert response.status_code == 400
    assert "不能为空" in response.json()["detail"]["message"]


def test_invalid_conference_and_year_are_rejected(client):
    bad_conference = client.post(
        "/api/papers",
        json={"title": "Valid Length Title", "conference": "WACV", "year": 2024},
    )
    assert bad_conference.status_code == 400
    assert bad_conference.json()["detail"]["code"] == "invalid_parameter"

    bad_year = client.post(
        "/api/papers",
        json={"title": "Valid Length Title", "conference": "CVPR", "year": 0},
    )
    assert bad_year.status_code == 400


def test_update_changes_fields_and_flags_code_scope(client, paper_factory):
    title = "Zip-NeRF: Anti-Aliased Grid-Based Neural Radiance Fields"
    paper = paper_factory(title, conference="ICCV", year=2023)

    response = client.patch(
        f"/api/papers/{paper['id']}",
        json={"conference": "ECCV", "year": 2024, "abstract": "补充的摘要内容。"},
    )
    assert response.status_code == 200
    body = response.json()
    # 编号保持入库时分配的值，但明确标记与当前会议年份不一致
    assert body["code"] == "ICCV-2023-0001"
    assert body["code_scope_mismatch"] is True
    assert body["code_note"] == "编号为入库时分配，与当前会议年份不一致"
    assert body["conference"] == "ECCV"
    assert body["year"] == 2024


def test_update_title_invalidates_system_keywords(client, paper_factory, temp_db):
    paper = paper_factory("Original Title Of A Long Paper")
    # 模拟阶段 5 已抽取系统关键词：直接写库，验证修改后会被清理
    add_system_keyword(
        temp_db,
        paper_id=paper["id"],
        name="object detection",
        version=KEYWORD_RULESET_VERSION,
    )
    set_meta(temp_db, "keyword_ruleset_version", KEYWORD_RULESET_VERSION)
    assert client.get(f"/api/papers/{paper['id']}").json()["system_keywords"] == [
        "object detection"
    ]

    response = client.patch(
        f"/api/papers/{paper['id']}", json={"title": "A Completely Different Title Now"}
    )
    assert response.status_code == 200
    body = response.json()
    # 题目变化使抽取结果失效：退回待处理并清空系统关键词
    assert body["keyword_status"] == "pending"
    assert body["system_keywords"] == []
    assert count_rows(temp_db, "paper_keyword") == 0


def test_delete_cascades_relations_and_keeps_code_unused(
    client, paper_factory, temp_db
):
    title = "High-Resolution Image Synthesis with Latent Diffusion Models"
    paper = paper_factory(title, source_keywords=["扩散生成模型"])
    paper_id = paper["id"]

    assert client.delete(f"/api/papers/{paper_id}").status_code == 204
    assert client.get(f"/api/papers/{paper_id}").status_code == 404

    # 关联被级联清理，关键词行本身保留（可能被其他论文引用）
    assert count_rows(temp_db, "paper_keyword", "paper_id = ?", (paper_id,)) == 0
    assert count_rows(temp_db, "paper_source", "paper_id = ?", (paper_id,)) == 0
    assert count_rows(temp_db, "keyword") == 1

    # 编号不复用：新建同一会议年份的论文拿到的是下一个序号
    next_paper = paper_factory("Another Paper With A Long Enough Title")
    assert next_paper["code"] == "CVPR-2024-0002"


def test_update_to_duplicate_is_rejected(client, paper_factory):
    first = paper_factory("First Paper With A Long Title")
    paper_factory("Second Paper With A Long Title")

    response = client.patch(
        f"/api/papers/{first['id']}", json={"title": "Second Paper With A Long Title"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_paper"


def test_normalize_title_is_conservative():
    assert normalize_title("Segment Anything") == "segment anything"
    assert normalize_title("  Segment   Anything.  ") == "segment anything"
    assert normalize_title("DETRs Beat YOLOs!") == "detrs beat yolos"
    # 不做词形还原，避免不同论文被误并
    assert normalize_title("Detectors") != normalize_title("Detector")


def test_dedup_key_shape():
    assert build_dedup_key("CVPR", 2024, "Some Title") == "CVPR|2024|some title"
