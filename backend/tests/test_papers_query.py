"""检索、组合筛选、排序与分页的验证。"""

from __future__ import annotations

from .helpers import add_system_keyword, insert_topic

# 12 篇可手工推算的样本：3 个会议 × 若干年份
SEED_ROWS: tuple[tuple[str, str, int], ...] = (
    ("Alpha Detection Network With Long Title", "CVPR", 2022),
    ("Beta Segmentation Framework With Long Title", "CVPR", 2023),
    ("Gamma Diffusion Model With Long Title", "CVPR", 2024),
    ("Delta Vision Language Model With Long Title", "CVPR", 2025),
    ("Epsilon Tracking Method With Long Title", "ICCV", 2023),
    ("Zeta NeRF Reconstruction With Long Title", "ICCV", 2023),
    ("Eta Multimodal Large Model With Long Title", "ICCV", 2025),
    ("Theta Pose Estimation With Long Title", "ECCV", 2022),
    ("Iota Medical Segmentation With Long Title", "ECCV", 2022),
    ("Kappa Adversarial Robustness With Long Title", "ECCV", 2024),
    ("Lambda Video Understanding With Long Title", "ECCV", 2024),
    ("Mu Self-Supervised Learning With Long Title", "CVPR", 2024),
)


def seed(client) -> None:
    """写入 12 篇样本记录。"""
    for title, conference, year in SEED_ROWS:
        response = client.post(
            "/api/papers",
            json={"title": title, "conference": conference, "year": year},
        )
        assert response.status_code == 201, response.text


def test_exact_match_on_title_and_code(client, paper_factory):
    paper_factory("Segment Anything In Detail")
    paper_factory("Another Completely Different Paper")

    by_title = client.get(
        "/api/papers", params={"q": "Segment Anything In Detail", "match": "exact"}
    ).json()
    assert by_title["total"] == 1

    # 精确匹配不接受子串
    partial = client.get(
        "/api/papers", params={"q": "Segment Anything", "match": "exact"}
    ).json()
    assert partial["total"] == 0

    by_code = client.get(
        "/api/papers", params={"q": "CVPR-2024-0002", "match": "exact"}
    ).json()
    assert by_code["total"] == 1
    assert by_code["items"][0]["code"] == "CVPR-2024-0002"


def test_fuzzy_match_covers_title_code_and_keyword(client, paper_factory):
    paper = paper_factory(
        "InternVL Scaling Up Vision Foundation Models",
        source_keywords=["多模态大模型"],
    )
    assert paper["code"] == "CVPR-2024-0001"

    assert client.get("/api/papers", params={"q": "vision foundation"}).json()[
        "total"
    ] == 1
    assert client.get("/api/papers", params={"q": "2024-0001"}).json()["total"] == 1
    assert client.get("/api/papers", params={"q": "多模态"}).json()["total"] == 1


def test_conference_filter_accepts_comma_and_repeated_params(client):
    seed(client)
    comma = client.get("/api/papers", params={"conference": "CVPR,ICCV"}).json()
    repeated = client.get(
        "/api/papers", params=[("conference", "CVPR"), ("conference", "ICCV")]
    ).json()

    assert comma["total"] == repeated["total"] == 8
    assert comma["scope"]["conferences"] == ["CVPR", "ICCV"]


def test_year_range_and_single_year_shorthand(client):
    seed(client)
    # 2023 与 2024 两个年份共 7 篇
    ranged = client.get(
        "/api/papers", params={"year_from": 2023, "year_to": 2024}
    ).json()
    assert ranged["total"] == 7

    assert client.get("/api/papers", params={"year": 2023}).json()["total"] == 3

    # year 与 year_from 同时出现时，显式的区间优先
    explicit = client.get(
        "/api/papers", params={"year": 2023, "year_from": 2022, "year_to": 2022}
    ).json()
    assert explicit["total"] == 3


def test_combined_filters(client):
    seed(client)
    # CVPR 与 ECCV 在 2024—2025：CVPR 两篇（2024）+ 一篇（2025）+ ECCV 两篇（2024）
    combined = client.get(
        "/api/papers",
        params={"conference": "CVPR,ECCV", "year_from": 2024, "year_to": 2025},
    ).json()
    assert combined["total"] == 5
    assert all(item["conference"] in ("CVPR", "ECCV") for item in combined["items"])
    assert all(item["year"] in (2024, 2025) for item in combined["items"])


def test_keyword_and_status_filters(client, paper_factory):
    paper_factory("Paper One About Detection", source_keywords=["目标检测"])
    paper_factory("Paper Two About Something Else")

    assert client.get("/api/papers", params={"keyword": "目标检测"}).json()[
        "total"
    ] == 1
    # 新建记录均为 review / pending
    assert client.get(
        "/api/papers", params={"data_status": "review"}
    ).json()["total"] == 2
    assert client.get(
        "/api/papers", params={"keyword_status": "pending"}
    ).json()["total"] == 2
    assert client.get(
        "/api/papers", params={"data_status": "complete"}
    ).json()["total"] == 0


def test_sorting_is_stable_and_ordered(client):
    seed(client)
    params = {"page_size": 100}

    by_year_desc = client.get(
        "/api/papers", params={**params, "sort": "year", "order": "desc"}
    ).json()
    years = [item["year"] for item in by_year_desc["items"]]
    assert years == sorted(years, reverse=True)

    by_code_asc = client.get(
        "/api/papers", params={**params, "sort": "code", "order": "asc"}
    ).json()
    codes = [item["code"] for item in by_code_asc["items"]]
    assert codes == sorted(codes)

    # 同一排序条件下重复请求顺序一致（稳定次级键为 id）
    again = client.get(
        "/api/papers", params={**params, "sort": "year", "order": "desc"}
    ).json()
    assert [item["id"] for item in by_year_desc["items"]] == [
        item["id"] for item in again["items"]
    ]


def test_pagination_boundaries(client):
    seed(client)

    first = client.get("/api/papers", params={"page": 1, "page_size": 5}).json()
    assert first["total"] == 12
    assert first["pages"] == 3
    assert len(first["items"]) == 5
    assert first["page"] == 1

    last = client.get("/api/papers", params={"page": 3, "page_size": 5}).json()
    assert len(last["items"]) == 2

    # 超出范围时收敛到最后一页，而不是返回空列表
    beyond = client.get("/api/papers", params={"page": 99, "page_size": 5}).json()
    assert beyond["page"] == 3
    assert len(beyond["items"]) == 2

    # 分页之间不重复、不遗漏
    seen: set[int] = set()
    for page in range(1, 4):
        chunk = client.get(
            "/api/papers", params={"page": page, "page_size": 5}
        ).json()
        for item in chunk["items"]:
            assert item["id"] not in seen
            seen.add(item["id"])
    assert len(seen) == 12


def test_invalid_query_parameters_return_400(client):
    cases = [
        {"year_from": 2025, "year_to": 2020},
        {"sort": "unknown_field"},
        {"order": "sideways"},
        {"match": "regex"},
        {"page": 0},
        {"page_size": 0},
        {"page_size": 1000},
        {"conference": "WACV"},
    ]
    for params in cases:
        response = client.get("/api/papers", params=params)
        assert response.status_code == 400, params
        assert response.json()["detail"]["code"] == "invalid_parameter", params


def test_related_papers_uses_system_keyword_topics(client, paper_factory, temp_db):
    """同主题检索依据系统关键词所属主题；作者关键词不参与，与统计口径一致。"""
    first = paper_factory("First Paper On A Shared Topic", source_keywords=["作者自填词"])
    second = paper_factory("Second Paper On A Shared Topic")
    third = paper_factory("Third Paper On Another Topic")

    shared_topic = insert_topic(temp_db, slug="shared-topic", name="共同主题")
    other_topic = insert_topic(
        temp_db, slug="other-topic", name="无关主题", sort_order=1
    )
    add_system_keyword(
        temp_db, paper_id=first["id"], name="共同主题", topic_id=shared_topic
    )
    add_system_keyword(
        temp_db, paper_id=second["id"], name="共同主题", topic_id=shared_topic
    )
    add_system_keyword(
        temp_db, paper_id=third["id"], name="无关主题", topic_id=other_topic
    )

    related = client.get(f"/api/papers/{first['id']}/related")
    assert related.status_code == 200
    titles = [item["title"] for item in related.json()["items"]]
    # 只返回共享同一主题的论文，不包含其他主题的论文
    assert titles == ["Second Paper On A Shared Topic"]


def test_related_papers_is_empty_without_system_keywords(client, paper_factory):
    """阶段 5 抽取系统关键词之前，同主题论文为空是正确结果，不用作者关键词兜底。"""
    paper = paper_factory(
        "A Paper With Only Author Keywords", source_keywords=["目标检测"]
    )
    assert client.get(f"/api/papers/{paper['id']}/related").json()["items"] == []


def test_list_includes_author_keywords_with_origin(client, paper_factory):
    paper_factory(
        "A Paper With Several Author Keywords",
        source_keywords=["目标检测", "语义分割"],
    )
    keywords = client.get("/api/papers").json()["items"][0]["keywords"]
    assert {item["origin"] for item in keywords} == {"author"}
    assert {item["name"] for item in keywords} == {"目标检测", "语义分割"}
    # 未归并到主题时如实标记为未归类
    assert all(item["topic"] is None for item in keywords)
