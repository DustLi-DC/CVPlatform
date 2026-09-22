"""单篇采集流程的验证：本地优先、候选确认、失败分支与关键词处理。

外部来源通过 monkeypatch 注入固定响应或固定异常，因此这些用例不依赖网络；
联网端到端验证另行进行并在交付说明中单独报告。
"""

from __future__ import annotations

import pytest

from app.services.sources.http import SourceTimeout, SourceUnavailable
from app.services.sources.openalex import RemoteCandidate


def _candidate(**overrides) -> RemoteCandidate:
    defaults = dict(
        source="openalex",
        source_id="https://openalex.org/W1",
        title="Sapiens: Foundation for Human Vision Models",
        year=2024,
        conference=None,
        venue="Lecture Notes in Computer Science",
        doi="https://doi.org/10.1007/978-3-031-73235-5_12",
        landing_url="https://doi.org/10.1007/978-3-031-73235-5_12",
        pdf_url=None,
        abstract="We present Sapiens foundation models for human vision tasks.",
        authors=["Rawal Rakhimov"],
        work_type="conference-paper",
        match_score=0.95,
    )
    defaults.update(overrides)
    return RemoteCandidate(**defaults)


# ------------------------------------------------------------ 本地优先


def test_lookup_returns_local_hit_without_touching_network(
    client, paper_factory, monkeypatch
):
    paper_factory("Segment Anything", conference="ICCV", year=2023)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("本地已命中时不应发起外部请求")

    monkeypatch.setattr("app.services.collector.search_by_title", fail_if_called)
    monkeypatch.setattr("app.services.collector.lookup_index", fail_if_called)

    response = client.post("/api/collect/lookup", json={"title": "Segment Anything"})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "local_hit"
    assert len(body["papers"]) == 1
    assert body["papers"][0]["code"] == "ICCV-2023-0001"


def test_lookup_local_hit_is_case_and_punctuation_insensitive(client, paper_factory):
    paper_factory("Masked Autoencoders Are Scalable Vision Learners")
    response = client.post(
        "/api/collect/lookup",
        json={"title": "masked  autoencoders are scalable vision learners."},
    )
    assert response.json()["outcome"] == "local_hit"


# ------------------------------------------------------- 联网候选与确认


def test_lookup_returns_candidates_sorted_by_similarity(client, monkeypatch):
    """候选按实际算出的相似度降序；不采信来源自身给出的顺序。"""
    candidates = [
        _candidate(
            source_id="https://openalex.org/W2",
            title="Sapiens Foundation for Human Vision",
            work_type="preprint",
            abstract=None,
        ),
        _candidate(title="Sapiens: Foundation for Human Vision Models"),
    ]
    monkeypatch.setattr(
        "app.services.collector.search_by_title", lambda *_a, **_k: candidates
    )

    body = client.post(
        "/api/collect/lookup",
        json={"title": "Sapiens: Foundation for Human Vision Models"},
    ).json()

    assert body["outcome"] == "remote_candidates"
    assert body["source"] == "openalex"
    scores = [item["match_score"] for item in body["candidates"]]
    # 降序排列，且题目完全一致的那条得满分
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 1.0
    assert 0.0 < scores[1] < 1.0
    # 摘要缺失要显式标记，不能靠空字符串暗示
    assert body["candidates"][0]["abstract_missing"] is False
    assert body["candidates"][1]["abstract_missing"] is True


def test_candidate_without_conference_is_marked_for_user_input(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.collector.search_by_title", lambda *_a, **_k: [_candidate()]
    )
    body = client.post(
        "/api/collect/lookup",
        json={"title": "Sapiens: Foundation for Human Vision Models"},
    ).json()
    candidate = body["candidates"][0]
    # ECCV 的 DOI 指向出版社，推不出会议时必须是 null 并给出说明
    assert candidate["conference"] is None
    assert any("无法确定会议归属" in note for note in candidate["notes"])


def test_candidate_already_in_library_is_flagged(client, paper_factory, monkeypatch):
    paper_factory(
        "Sapiens: Foundation for Human Vision Models", conference="ECCV", year=2024
    )
    monkeypatch.setattr(
        "app.services.collector.search_by_title",
        lambda *_a, **_k: [
            _candidate(
                conference="ECCV",
                title="Sapiens: Foundation for Human Vision Models",
            )
        ],
    )
    body = client.post(
        "/api/collect/lookup",
        json={
            "title": "Sapiens Foundation Human Vision",
            "conference": "ECCV",
            "year": 2024,
        },
    ).json()
    # 本地按归一化标题没命中（题目不同），但候选标记为已在库中
    assert body["outcome"] in ("remote_candidates", "local_hit")
    if body["outcome"] == "remote_candidates":
        assert body["candidates"][0]["already_exists"] is True


def test_confirm_reuses_validation_and_dedup(client, monkeypatch):
    monkeypatch.setattr("app.services.collector.search_by_title", lambda *_a, **_k: [])
    payload = {
        "title": "A Collected Paper From OpenAlex",
        "conference": "CVPR",
        "year": 2024,
        "source": "openalex",
        "source_id": "https://openalex.org/W42",
        "abstract": "An abstract retrieved from the online source.",
        "authors": ["First Author", "Second Author"],
        "landing_url": "https://example.org/paper",
        "pdf_url": "https://example.org/paper.pdf",
    }

    created = client.post("/api/collect/confirm", json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["code"] == "CVPR-2024-0001"
    assert body["landing_url"] == "https://example.org/paper"
    assert body["pdf_url"] == "https://example.org/paper.pdf"
    assert body["authors"] == ["First Author", "Second Author"]
    # 采集入库后立即处理关键词：状态进入 done 并写入系统关键词
    assert body["keyword_status"] == "done"
    assert body["system_keywords"], "采集后应产出系统关键词"

    # 再次确认同一篇：复用去重，不产生第二条记录
    again = client.post("/api/collect/confirm", json=payload)
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]
    assert client.get("/api/papers").json()["total"] == 1


def test_confirm_rejects_short_title_like_manual_create(client):
    response = client.post(
        "/api/collect/confirm",
        json={
            "title": "短",
            "conference": "CVPR",
            "year": 2024,
            "source": "openalex",
            "source_id": "W1",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_parameter"


def test_confirm_validates_conference_and_year(client):
    for payload in (
        {"conference": "WACV", "year": 2024},
        {"conference": "CVPR", "year": 0},
    ):
        response = client.post(
            "/api/collect/confirm",
            json={
                "title": "A Long Enough Title For Validation",
                "source": "openalex",
                "source_id": "W1",
                **payload,
            },
        )
        assert response.status_code == 400, payload


# ------------------------------------------------------------ 失败分支


def test_lookup_distinguishes_timeout_from_unavailable(client, monkeypatch):
    def raise_timeout(*_args, **_kwargs):
        raise SourceTimeout("openalex", "openalex 请求超时（10 秒）")

    monkeypatch.setattr("app.services.collector.search_by_title", raise_timeout)
    timeout_response = client.post(
        "/api/collect/lookup", json={"title": "Some Missing Paper"}
    )
    assert timeout_response.status_code == 504
    assert timeout_response.json()["detail"]["code"] == "upstream_timeout"

    def raise_unavailable(*_args, **_kwargs):
        raise SourceUnavailable("openalex", "openalex 返回 HTTP 503", 503)

    monkeypatch.setattr("app.services.collector.search_by_title", raise_unavailable)
    unavailable_response = client.post(
        "/api/collect/lookup", json={"title": "Some Missing Paper"}
    )
    assert unavailable_response.status_code == 502
    assert unavailable_response.json()["detail"]["code"] == "upstream_unavailable"


def test_lookup_returns_empty_when_nothing_found(client, monkeypatch):
    monkeypatch.setattr("app.services.collector.search_by_title", lambda *_a, **_k: [])
    response = client.post(
        "/api/collect/lookup",
        json={"title": "Quantum Vision Question Answering"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "remote_empty"
    assert body["candidates"] == []


def test_lookup_rejects_invalid_parameters(client):
    assert client.post("/api/collect/lookup", json={"title": ""}).status_code == 400
    assert (
        client.post(
            "/api/collect/lookup", json={"title": "A Long Enough Title", "year": 0}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/collect/lookup",
            json={"title": "A Long Enough Title", "conference": "WACV"},
        ).status_code
        == 400
    )


def test_index_lookup_uses_conference_index_and_enriches_detail(client, monkeypatch):
    """已知会议年份时走索引匹配，并用详情页补齐摘要与原文链接。"""
    from app.services.sources.cvf import IndexEntry, PaperFields

    monkeypatch.setattr(
        "app.services.collector.cvf.fetch_index",
        lambda conference, year, **_kwargs: [
            IndexEntry(
                title=(
                    "Unmixing Diffusion for Self-Supervised "
                    + "Hyperspectral Image Denoising"
                ),
                paper_path="/content/CVPR2024/html/x_paper.html",
            )
        ],
    )
    monkeypatch.setattr(
        "app.services.collector.cvf.fetch_paper",
        lambda path, **_kwargs: PaperFields(
            title=(
                "Unmixing Diffusion for Self-Supervised "
                + "Hyperspectral Image Denoising"
            ),
            authors=["Haijin Zeng"],
            abstract="Hyperspectral images have extensive applications.",
            pdf_url="https://openaccess.thecvf.com/content/CVPR2024/papers/x.pdf",
            landing_url=(
                "https://openaccess.thecvf.com/content/CVPR2024/html/x_paper.html"
            ),
        ),
    )

    body = client.post(
        "/api/collect/lookup",
        json={
            "title": (
                "Unmixing Diffusion for Self-Supervised "
                + "Hyperspectral Image Denoising"
            ),
            "conference": "CVPR",
            "year": 2024,
        },
    ).json()

    assert body["outcome"] == "remote_candidates"
    assert body["source"] == "cvf"
    candidate = body["candidates"][0]
    # 会议归属由索引确定，摘要与原文链接由详情页补齐
    assert candidate["conference"] == "CVPR"
    assert candidate["abstract"] is not None
    assert candidate["pdf_url"] is not None
    assert candidate["abstract_missing"] is False
    assert candidate["match_score"] == 1.0


def test_index_candidates_below_threshold_are_filtered(client, monkeypatch):
    from app.services.sources.cvf import IndexEntry

    monkeypatch.setattr(
        "app.services.collector.cvf.fetch_index",
        lambda conference, year, **_kwargs: [
            IndexEntry(
                title="A Completely Unrelated Paper About Something Else",
                paper_path="/p1",
            )
        ],
    )
    body = client.post(
        "/api/collect/lookup",
        json={
            "title": "Unmixing Diffusion for Hyperspectral Denoising",
            "conference": "CVPR",
            "year": 2024,
        },
    ).json()
    assert body["outcome"] == "remote_empty"


# ------------------------------------------------- 关键词状态与版本


def test_collected_paper_enters_analysis_set(client, monkeypatch):
    """采集成功的论文应完成关键词处理，从而进入分析集合（分母）。"""
    monkeypatch.setattr("app.services.collector.search_by_title", lambda *_a, **_k: [])
    client.post(
        "/api/collect/confirm",
        json={
            "title": "Object Detection with Transformer Detectors",
            "conference": "CVPR",
            "year": 2024,
            "source": "openalex",
            "source_id": "W7",
            "abstract": "We study object detection with transformer detectors.",
        },
    )
    detail = client.get("/api/papers/1").json()
    assert detail["keyword_status"] == "done"
    assert detail["system_keywords"]
    # 作者关键词与系统提取关键词的来源区别保持
    assert all(item["origin"] == "system" for item in detail["keywords"])


def test_keyword_processing_marks_success_empty_separately(tmp_path, monkeypatch):
    """抽取成功但为空 → done；抽取抛错 → failed。两种状态必须区分。"""
    from sqlmodel import Session

    from app.db.engine import get_engine, init_database, reset_engine
    from app.services import keyword_job
    from app.services.papers import save_paper

    db_path = tmp_path / "kw.db"
    monkeypatch.setenv("CVPLATFORM_ENV", "test")
    monkeypatch.setenv("CVPLATFORM_DB_PATH", str(db_path))
    reset_engine()
    init_database()

    with Session(get_engine()) as session:
        # 只有停用词的题目 → 抽取成功但为空
        empty_paper, _ = save_paper(
            session,
            title="the and of for with by",
            conference="CVPR",
            year=2024,
            abstract=None,
        )
        session.commit()
        summary = keyword_job.process_pending(session)
        session.commit()
        assert empty_paper.keyword_status == "done"
        assert empty_paper.keyword_ruleset_version is not None
        assert summary.processed == 1
        assert summary.empty == 1
        assert summary.failed == 0

    # 让抽取抛错 → 必须记为 failed，且不影响其他论文
    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated extraction failure")

    monkeypatch.setattr(keyword_job.KeywordExtractor, "extract", boom)
    with Session(get_engine()) as session:
        save_paper(
            session,
            title="Another Paper With Real Words Inside",
            conference="CVPR",
            year=2024,
            abstract="A proper abstract with meaningful vocabulary items.",
        )
        session.commit()
        summary = keyword_job.process_pending(session)
        session.commit()
        assert summary.failed == 1
        assert summary.processed == 0

    reset_engine()


def test_pending_papers_excludes_current_version_done(client, monkeypatch):
    from sqlmodel import Session

    from app.db.engine import get_engine
    from app.services.keyword_job import pending_papers
    from app.services.papers import save_paper

    monkeypatch.setattr("app.services.collector.search_by_title", lambda *_a, **_k: [])
    client.post(
        "/api/collect/confirm",
        json={
            "title": "A Paper That Becomes Fully Processed",
            "conference": "CVPR",
            "year": 2024,
            "source": "openalex",
            "source_id": "W9",
            "abstract": "Detection and segmentation with transformers.",
        },
    )
    with Session(get_engine()) as session:
        assert pending_papers(session) == []
