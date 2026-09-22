"""批量导入与任务的验证（阶段 6 任务第 1、2、3、5、6 条）。

外部来源一律用固定响应替身，因此这些用例不联网；
真实数据采集的结果另行报告。
"""

from __future__ import annotations

import io
import threading
import time

import pytest
from sqlmodel import Session, select

from app.models.entities import CollectionTask, CollectionTaskItem
from app.services import importer, tasks
from app.services.index_cache import IndexedPaper, IndexCache
from app.services.sources.cvf import PaperFields

# ------------------------------------------------------------ 文件解析


def test_parse_txt_skips_blank_lines_and_reports_duplicates():
    content = (
        "High-Resolution Image Synthesis with Latent Diffusion Models\n"
        "\n"
        "VideoMAE V2: Scaling Video Masked Autoencoders with Dual Masking\n"
        "   \n"
        "high-resolution image synthesis with latent diffusion models\n"  # 行内重复
        "短题目\n"  # 过短
    ).encode("utf-8")
    result = importer.parse_file("titles.txt", content)

    assert result.file_format == "txt"
    assert result.blank_count == 2
    assert result.duplicate_in_file_count == 1
    assert result.invalid_count == 1
    assert result.valid_count == 2
    assert result.importable_count == 2
    # 错误行保留原始行号，便于回到文件核对
    invalid = [row for row in result.rows if row.status == "invalid"]
    assert invalid[0].line_no == 6


def test_parse_txt_handles_bom():
    content = "\ufeffA Paper With A Byte Order Mark Inside".encode("utf-8")
    result = importer.parse_file("titles.txt", content)
    assert result.valid_count == 1
    assert result.rows[0].title == "A Paper With A Byte Order Mark Inside"


def test_parse_csv_reads_optional_columns():
    content = (
        "title,conference,year\n"
        'DETRs Beat YOLOs on Real-time Object Detection,CVPR,2024\n'
        '"A Title, With A Comma Inside",ICCV,2023\n'
        "Sapiens: Foundation for Human Vision Models,,\n"
    ).encode("utf-8")
    result = importer.parse_file("papers.csv", content)

    assert result.file_format == "csv"
    assert result.valid_count == 3
    # 引号内的逗号不能被当成列分隔
    assert result.rows[1].title == "A Title, With A Comma Inside"
    assert result.rows[1].conference == "ICCV"
    # 留空的会议与年份保持 None，由索引匹配决定
    assert result.rows[2].conference is None
    assert result.rows[2].year is None


def test_parse_csv_rejects_bad_conference_and_year():
    content = (
        "title,conference,year\n"
        "A Valid Length Paper Title,WACV,2024\n"
        "Another Valid Length Title,CVPR,not-a-year\n"
    ).encode("utf-8")
    result = importer.parse_file("papers.csv", content)
    assert result.invalid_count == 2
    assert result.valid_count == 0
    messages = " ".join(row.message or "" for row in result.rows)
    assert "conference" in messages
    assert "year" in messages


def test_parse_csv_requires_title_column():
    with pytest.raises(importer.ImportFileError) as error:
        importer.parse_file("papers.csv", b"name,venue\nSomething,CVPR\n")
    assert error.value.code == "missing_title_column"


def test_reject_unsupported_type_and_empty_file():
    with pytest.raises(importer.ImportFileError) as error:
        importer.parse_file("papers.xlsx", b"whatever")
    assert error.value.code == "unsupported_file_type"

    with pytest.raises(importer.ImportFileError) as empty:
        importer.parse_file("papers.txt", b"")
    assert empty.value.code == "empty_file"


def test_reject_file_over_row_limit(monkeypatch):
    """行数超过上限时直接拒绝，并给出明确提示。"""
    titles = [f"Paper Title Number {index} For Row Limit" for index in range(3)]
    content = chr(10).join(titles).encode()
    # importer 在导入时绑定了常量，因此按「使用位置」打桩
    monkeypatch.setattr(importer, "IMPORT_MAX_ROWS", 2)
    with pytest.raises(importer.ImportFileError) as error:
        importer.parse_file("titles.txt", content)
    assert error.value.code == "too_many_rows"


def test_reject_file_over_size_limit(monkeypatch):
    monkeypatch.setattr(importer, "IMPORT_MAX_BYTES", 10)
    with pytest.raises(importer.ImportFileError) as error:
        importer.parse_file("titles.txt", b"A Paper Title Longer Than Ten Bytes")
    assert error.value.code == "file_too_large"


def test_gb18030_encoded_file_is_decoded():
    content = "中文题目也需要能够导入".encode("gb18030")
    result = importer.parse_file("titles.txt", content)
    assert result.rows[0].title == "中文题目也需要能够导入"


# --------------------------------------------------------- 抽样规则


def test_sampling_is_systematic_and_reproducible():
    from app.services.harvest import plan_sampling

    entries = [
        IndexedPaper(
            title=f"Paper Number {index}",
            conference="CVPR",
            year=2024,
            paper_path=f"/p/{index}",
            landing_url=f"https://example.org/{index}",
        )
        for index in range(1000)
    ]
    plan = plan_sampling(entries, conference="CVPR", year=2024, limit=200)
    assert plan.total_available == 1000
    assert plan.stride == 5
    assert len(plan.selected) == 200
    # 等距抽样：第 k 个取的是第 k*stride 条
    assert plan.selected[0].title == "Paper Number 0"
    assert plan.selected[1].title == "Paper Number 5"
    # 可复现：同样输入得到同样结果
    again = plan_sampling(entries, conference="CVPR", year=2024, limit=200)
    assert [item.paper_path for item in again.selected] == [
        item.paper_path for item in plan.selected
    ]


def test_sampling_handles_small_index():
    from app.services.harvest import plan_sampling

    entries = [
        IndexedPaper(
            title=f"Only {index}",
            conference="ECCV",
            year="2022",
            paper_path=f"/p/{index}",
            landing_url="https://example.org",
        )
        for index in range(3)
    ]
    plan = plan_sampling(entries, conference="ECCV", year=2022, limit=200)
    assert plan.stride == 1
    assert len(plan.selected) == 3


# ------------------------------------------------------------ 任务接口


def _make_index(*titles: str) -> IndexedPaper:
    return IndexedPaper(
        title=titles[0],
        conference="CVPR",
        year=2024,
        paper_path="/content/CVPR2024/html/x_paper.html",
        landing_url="https://openaccess.thecvf.com/content/CVPR2024/html/x_paper.html",
    )


def _stub_sources(
    monkeypatch, *, hit_titles: list[str], abstract: str | None = "An abstract."
):
    """把所有外部来源替换成固定替身。

    索引按 cvf.IndexEntry 的真实结构返回，因此 IndexCache 会正常填充缓存，
    match() 也就能命中——如果只替换 load()，match() 会因为缓存为空而落回
    真实在线检索，测试会变慢且依赖网络。
    """
    from app.services.sources.cvf import IndexEntry

    entries = [
        IndexEntry(
            title=title,
            paper_path=f"/content/CVPR2024/html/{index}_paper.html",
        )
        for index, title in enumerate(hit_titles)
    ]
    monkeypatch.setattr(
        "app.services.index_cache.cvf.fetch_index",
        lambda conference, year, **kwargs: entries,
    )
    monkeypatch.setattr(
        "app.services.index_cache.ecva.fetch_index",
        lambda year, **kwargs: [],
    )

    cache = IndexCache()
    monkeypatch.setattr("app.services.tasks.shared_cache", cache)

    def fake_fetch_paper(paper_path, **_kwargs):
        entry = next(item for item in entries if item.paper_path == paper_path)
        return PaperFields(
            title=entry.title,
            authors=["First Author"],
            abstract=abstract,
            pdf_url="https://openaccess.thecvf.com/content/CVPR2024/papers/x.pdf",
            landing_url=f"https://openaccess.thecvf.com{paper_path}",
        )

    monkeypatch.setattr("app.services.sources.cvf.fetch_paper", fake_fetch_paper)
    return cache


def _upload(client, content: str, name: str = "titles.txt"):
    return client.post(
        "/api/import/preview",
        files={"file": (name, io.BytesIO(content.encode("utf-8")), "text/plain")},
    )


def test_preview_does_not_write_to_database(client):
    response = _upload(client, "A Preview Only Paper Title Here\n")
    assert response.status_code == 200
    body = response.json()
    assert body["valid_count"] == 1
    assert body["importable_count"] == 1
    # 预览阶段不写库
    assert client.get("/api/papers").json()["total"] == 0
    assert client.get("/api/import/tasks").json()["total"] == 0


def test_template_endpoint_describes_format(client):
    body = client.get("/api/import/template").json()
    assert "title" in body["csv_template"]
    assert body["max_rows"] == 500
    assert {note["name"] for note in body["field_notes"]} == {
        "title",
        "conference",
        "year",
    }


def test_preview_rejects_unsupported_type(client):
    response = client.post(
        "/api/import/preview",
        files={
            "file": ("papers.xlsx", io.BytesIO(b"data"), "application/vnd.ms-excel")
        },
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"


def test_all_success_import(client, monkeypatch, temp_db):
    """全部成功：每条都进入论文库并产出关键词。"""
    titles = [
        "Unmixing Diffusion for Hyperspectral Image Denoising",
        "Vision Transformer Object Detection With Long Title",
    ]
    _stub_sources(monkeypatch, hit_titles=titles)

    response = client.post(
        "/api/import/tasks",
        files={
            "file": ("titles.txt", io.BytesIO("\n".join(titles).encode()), "text/plain")
        },
    )
    assert response.status_code == 202
    task_id = response.json()["id"]

    payload = _wait_for_task(client, task_id)
    assert payload["status"] == "success"
    assert payload["success_count"] == 2
    assert payload["failed_count"] == 0
    assert payload["duplicate_count"] == 0
    assert payload["pending_count"] == 0
    # 计数来自明细统计，与论文库一致
    assert client.get("/api/papers").json()["total"] == 2
    detail = client.get(f"/api/import/tasks/{task_id}").json()
    assert all(item["status"] == "success" for item in detail["items"])
    assert all(item["message"] and "编号" in item["message"] for item in detail["items"])


def test_duplicate_input_is_marked_not_reimported(client, monkeypatch, temp_db):
    """重复输入：第二次记为重复并指出已存在的编号，不产生第二条记录。"""
    title = "Unmixing Diffusion for Hyperspectral Image Denoising"
    _stub_sources(monkeypatch, hit_titles=[title])

    first = client.post(
        "/api/import/tasks",
        files={"file": ("a.txt", io.BytesIO(title.encode()), "text/plain")},
    ).json()
    _wait_for_task(client, first["id"])

    second = client.post(
        "/api/import/tasks",
        files={"file": ("b.txt", io.BytesIO(title.encode()), "text/plain")},
    ).json()
    payload = _wait_for_task(client, second["id"])

    assert payload["duplicate_count"] == 1
    assert payload["success_count"] == 0
    detail = client.get(f"/api/import/tasks/{second['id']}").json()
    assert "已存在于论文库" in detail["items"][0]["message"]
    assert detail["items"][0]["duplicate_of_paper_id"] is not None
    assert client.get("/api/papers").json()["total"] == 1


def test_partial_failure_import(client, monkeypatch, temp_db):
    """部分失败：成功与失败分开计数，失败带原因。"""
    matched = "Unmixing Diffusion for Hyperspectral Image Denoising"
    _stub_sources(monkeypatch, hit_titles=[matched])

    content = matched + "\nA Totally Unrelated Paper Title Not In Any Index\n"
    task = client.post(
        "/api/import/tasks",
        files={"file": ("mixed.txt", io.BytesIO(content.encode()), "text/plain")},
    ).json()
    payload = _wait_for_task(client, task["id"])

    assert payload["status"] == "partial"
    assert payload["success_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["success_count"] + payload["failed_count"] == payload["total_count"]

    detail = client.get(f"/api/import/tasks/{task['id']}").json()
    failed = [item for item in detail["items"] if item["status"] == "failed"]
    # 失败原因要能看出是「没找到」还是「候选需人工确认」，不能含糊
    assert "没有找到匹配" in (failed[0]["message"] or "")


def test_all_failure_import(client, monkeypatch, temp_db):
    """全部失败：任务状态为 failed，且不产生论文记录。"""
    _stub_sources(monkeypatch, hit_titles=[])
    monkeypatch.setattr(
        "app.services.tasks.lookup",
        lambda *a, **k: type("O", (), {"outcome": "remote_empty", "message": None,
                                      "candidates": []})(),
    )
    task = client.post(
        "/api/import/tasks",
        files={
            "file": (
                "none.txt",
                io.BytesIO(b"Nothing Matches This Title At All\n"),
                "text/plain",
            )
        },
    ).json()
    payload = _wait_for_task(client, task["id"])

    assert payload["status"] == "failed"
    assert payload["failed_count"] == 1
    assert client.get("/api/papers").json()["total"] == 0


def test_retry_failed_items_keeps_successes(client, monkeypatch, temp_db):
    """重试失败条目：只处理失败项，成功项不动，仍走去重。"""
    matched = "Unmixing Diffusion for Hyperspectral Image Denoising"
    _stub_sources(monkeypatch, hit_titles=[matched])
    monkeypatch.setattr(
        "app.services.tasks.lookup",
        lambda *a, **k: type("O", (), {"outcome": "remote_empty", "message": None,
                                      "candidates": []})(),
    )

    content = matched + "\nAnother Unmatched Paper Title For Retry\n"
    task = client.post(
        "/api/import/tasks",
        files={"file": ("retry.txt", io.BytesIO(content.encode()), "text/plain")},
    ).json()
    before = _wait_for_task(client, task["id"])
    assert before["failed_count"] == 1
    assert before["success_count"] == 1

    # 让失败项这次可命中，再重试
    _stub_sources(
        monkeypatch,
        hit_titles=[matched, "Another Unmatched Paper Title For Retry"],
    )
    resumed = client.post(f"/api/import/tasks/{task['id']}/retry")
    assert resumed.status_code == 200
    after = _wait_for_task(client, task["id"])

    assert after["status"] == "success"
    assert after["success_count"] == 2
    assert after["failed_count"] == 0
    # 成功项没有被重复处理：论文总数是 2 而不是 3
    assert client.get("/api/papers").json()["total"] == 2
    assert client.get("/api/import/tasks").json()["total"] == 1


def test_retry_without_failures_is_rejected(client, monkeypatch, temp_db):
    title = "Unmixing Diffusion for Hyperspectral Image Denoising"
    _stub_sources(monkeypatch, hit_titles=[title])
    task = client.post(
        "/api/import/tasks",
        files={"file": ("ok.txt", io.BytesIO(title.encode()), "text/plain")},
    ).json()
    _wait_for_task(client, task["id"])

    response = client.post(f"/api/import/tasks/{task['id']}/retry")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "task_not_resumable"


def test_restart_recovery_marks_interrupted_and_resumes(client, monkeypatch, temp_db):
    """重启恢复：运行中的任务收敛为 interrupted，未完成明细退回 pending 后可续跑。"""
    titles = [
        "Unmixing Diffusion for Hyperspectral Image Denoising",
        "Vision Transformer Object Detection With Long Title",
    ]
    _stub_sources(monkeypatch, hit_titles=titles)

    # 直接构造一个「处理中被中断」的任务：一条成功、一条仍在运行
    with Session(_engine()) as session:
        task = CollectionTask(
            kind="batch",
            file_name="interrupted.txt",
            file_format="txt",
            total_count=2,
            status="running",
            message="正在处理…",
            created_at="2026-01-01T00:00:00Z",
        )
        session.add(task)
        session.flush()
        session.add(
            CollectionTaskItem(
                task_id=task.id or 0, line_no=1, input_title=titles[0],
                status="success", created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        session.add(
            CollectionTaskItem(
                task_id=task.id or 0, line_no=2, input_title=titles[1],
                status="running", created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        session.commit()
        task_id = task.id or 0

    with Session(_engine()) as session:
        recovered = tasks.recover_interrupted(session)
        session.commit()
        assert task_id in recovered
        task = session.get(CollectionTask, task_id)
        assert task is not None
        assert task.status == "interrupted"
        assert task.pending_count == 1
        assert task.success_count == 1
        assert task.running_count == 0
        assert "服务重启" in (task.message or "")

    # 继续处理：只补未完成的那条
    response = client.post(f"/api/import/tasks/{task_id}/resume")
    assert response.status_code == 200
    payload = _wait_for_task(client, task_id)
    assert payload["status"] == "success"
    assert payload["success_count"] == 2

    # 这条用例里的「成功」明细是手工构造的（只改了状态、没有对应论文记录），
    # 因此续跑只补了第 2 条，论文库中应恰好有 1 篇。
    # 关键是续跑没有重复处理已完成的那条：总成功数为 2 而不是 4。
    assert client.get("/api/papers").json()["total"] == 1
    detail = client.get(f"/api/import/tasks/{task_id}").json()
    assert [item["status"] for item in detail["items"]] == ["success", "success"]
    assert detail["items"][0]["attempts"] == 0  # 续跑没有再碰第 1 条


def test_task_and_items_are_queryable_after_refresh(client, monkeypatch, temp_db):
    """任务与明细持久化：新会话（模拟刷新）仍能查到。"""
    title = "Unmixing Diffusion for Hyperspectral Image Denoising"
    _stub_sources(monkeypatch, hit_titles=[title])
    task = client.post(
        "/api/import/tasks",
        files={"file": ("persist.txt", io.BytesIO(title.encode()), "text/plain")},
    ).json()
    _wait_for_task(client, task["id"])

    listing = client.get("/api/import/tasks").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == task["id"]

    filtered = client.get(
        f"/api/import/tasks/{task['id']}", params={"item_status": "success"}
    ).json()
    assert len(filtered["items"]) == 1

    bad = client.get(f"/api/import/tasks/{task['id']}", params={"item_status": "weird"})
    assert bad.status_code == 400


# ------------------------------------------------------------------ 工具


def _engine():
    from app.db.engine import get_engine

    return get_engine()


def _wait_for_task(client, task_id: int, *, timeout: float = 30.0) -> dict:
    """等待后台任务进入终态；超时则把当前状态返回，便于断言失败时看清原因。"""
    deadline = time.monotonic() + timeout
    payload: dict = {}
    while time.monotonic() < deadline:
        payload = client.get(f"/api/import/tasks/{task_id}").json()
        if payload["status"] in ("success", "partial", "failed", "interrupted"):
            # 任务线程可能刚写完状态但计数还在更新，留一拍再取一次
            time.sleep(0.15)
            payload = client.get(f"/api/import/tasks/{task_id}").json()
            return payload
        time.sleep(0.1)
    return payload


def test_index_cache_match_does_not_deadlock():
    """match() 内部不能重复获取同一把非重入锁。

    曾经 match() 在持锁状态下调用 cached_keys()，而后者又去拿同一把锁，
    导致整条任务处理线程永久卡住（表现为任务一直停在「运行中」）。
    """
    from app.services.index_cache import IndexCache, IndexedPaper

    cache = IndexCache()
    cache._entries[("CVPR", 2024)] = [
        IndexedPaper(
            title="A Cached Paper Title",
            conference="CVPR",
            year=2024,
            paper_path="/p/1",
            landing_url="https://example.org/1",
        )
    ]
    cache._by_normalized[("CVPR", 2024)] = {
        "a cached paper title": cache._entries[("CVPR", 2024)][0]
    }

    done = threading.Event()

    def run():
        hit, score = cache.match("A Cached Paper Title")
        assert hit is not None and score == 1.0
        # 顺带覆盖 cached_keys() 自身
        assert cache.cached_keys() == [("CVPR", 2024)]
        done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert done.wait(timeout=5.0), "match() 出现死锁，未在 5 秒内返回"


def test_index_cache_match_is_safe_with_empty_cache():
    from app.services.index_cache import IndexCache

    cache = IndexCache()
    hit, score = cache.match("Nothing Is Cached Yet")
    assert hit is None
    assert score == 0.0

def test_similar_title_is_not_treated_as_duplicate(client, monkeypatch, temp_db):
    """标题相近但不是同一篇论文时，不能被判成重复而跳过。

    回归用例：模糊检索曾把「DA-VPT: Semantic-Guided Visual Prompt Tuning …」
    当成「Visual Prompt Tuning」的重复。
    """
    from sqlmodel import Session

    from app.services.papers import save_paper

    with Session(_engine()) as session:
        save_paper(
            session,
            title="DA-VPT: Semantic-Guided Visual Prompt Tuning for Vision Transformers",
            conference="CVPR",
            year=2025,
            abstract="A different paper that merely shares a phrase.",
        )
        session.commit()

    _stub_sources(monkeypatch, hit_titles=["Visual Prompt Tuning"])
    task = client.post(
        "/api/import/tasks",
        files={"file": ("vpt.txt", io.BytesIO(b"Visual Prompt Tuning"), "text/plain")},
    ).json()
    payload = _wait_for_task(client, task["id"])

    # 应导入成功而不是被判为重复
    assert payload["duplicate_count"] == 0, payload
    assert payload["success_count"] == 1, payload
    assert client.get("/api/papers").json()["total"] == 2


def test_exact_same_title_in_same_scope_is_duplicate(client, monkeypatch, temp_db):
    """同一会议年份、同一题目才算重复。"""
    from sqlmodel import Session

    from app.services.papers import save_paper

    with Session(_engine()) as session:
        save_paper(
            session,
            title="Unmixing Diffusion for Hyperspectral Image Denoising",
            conference="CVPR",
            year=2024,
            abstract="A.",
        )
        session.commit()

    _stub_sources(monkeypatch, hit_titles=["Unmixing Diffusion for Hyperspectral Image Denoising"])
    task = client.post(
        "/api/import/tasks",
        files={"file": ("dup.txt", io.BytesIO(
            b"Unmixing Diffusion for Hyperspectral Image Denoising"), "text/plain")},
    ).json()
    payload = _wait_for_task(client, task["id"])
    assert payload["duplicate_count"] == 1, payload
    assert payload["success_count"] == 0, payload

def test_known_conference_year_loads_index_without_preloading(client, monkeypatch, temp_db):
    """会议年份已在文件里给出时，也必须自行载入索引来定位详情页。

    回归用例：曾经假设索引已被预加载（采集命令行恰好先载入了索引所以没暴露），
    换个进程或换条路径就会出现「索引中未找到对应条目」的假失败。
    """
    title = "Unmixing Diffusion for Hyperspectral Image Denoising"
    _stub_sources(monkeypatch, hit_titles=[title])

    content = chr(10).join(["title,conference,year", f"{title},CVPR,2024", ""])
    task = client.post(
        "/api/import/tasks",
        files={"file": ("scoped.csv", io.BytesIO(content.encode()), "text/csv")},
    ).json()
    payload = _wait_for_task(client, task["id"])

    assert payload["failed_count"] == 0, payload
    assert payload["success_count"] == 1, payload
