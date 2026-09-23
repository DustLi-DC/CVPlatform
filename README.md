# CVPlatform
| 这个作业属于哪个课程 | [2601_FZU_SE社区-CSDN社区云](https://bbs.csdn.net/forums/2601_CS_SE_FZU) |
| -------------------- | ------------------------------------------------------------ |
| 这个作业要求在哪里   | [软件工程实践第二次作业——与AI结对编程（顶会热词统计）-CSDN社区](https://bbs.csdn.net/topics/620526318) |
| 这个作业的目标       | 运用 NABCD 分析需求，与 AI 协作完成计算机视觉顶会论文分析平台的原型设计、编码、测试和云端部署，并记录人工决策与验证过程 |
| 学号/姓名            | 102400226/石华波                                             |
| 其他参考文献         | 《构建之法》；CVF Open Access；ECVA；Hugging Face ai-conferences 公开数据集，具体入口见文末 |

## 
计算机视觉顶会论文分析平台（课程作业）。把 CVPR、ICCV、ECCV 的论文题目与摘要集中起来，
用**关键词统计**回答三个问题：哪些方向在被反复研究、它们在几年里怎么变、以及这些方向上有哪些论文可读。

面向刚接触计算机视觉的同学：先看榜单与图谱建立整体印象，再顺着热词进入论文列表与详情精读。
结果只描述「本平台采集到的这个样本」，不等同于整届大会或整个领域的结论。

当前版本 **1.0.0**：仓库带 `1.0.0` 标签，发布包由 `deploy/make_release.sh 1.0.0 [--with-db]`
在本机生成（`data/release/` 下，已被 Git 忽略）。

## 五项核心能力

| # | 能力 | 入口 |
|---|---|---|
| 1 | 单篇采集 / 批量导入，产出摘要、关键词与原文链接 | 采集与导入 `/collect` |
| 2 | 论文增删改查；本地未命中时联网检索候选 | 论文管理 `/papers`、详情 `/papers/:id` |
| 3 | Top 10 热门方向（按去重关联论文数） | 热门方向总览 `/` |
| 4 | 可点击的关键词共现图谱 | 热门方向总览 `/` |
| 5 | CVPR / ICCV / ECCV 多年热度比较动画，可导出 GIF | 热度走势对比 `/trends` |

## 开发环境（本机实测版本）

- Python 3.12.6（项目根目录 `.venv`，与系统 Python 隔离）
- Node.js v24.15.0、npm 11.12.1

## 技术栈与运行形态

- 后端：Python 3.12、FastAPI、Uvicorn、SQLModel、SQLite（WAL）；**单 worker**，后台任务单线程串行执行。
- 前端：Vue 3、TypeScript、Vite、Vue Router、ECharts（按需注册、异步加载）、
  gifenc（MIT、无传递依赖，**仅在点「导出 GIF」时**动态加载，首屏与主包不携带）。
- 生产：华为云 Ubuntu 24.04（2 核 / 2 GB / 2 Mbps），代码放 `/opt/cvplatform`，
  数据库放 `/var/lib/cvplatform`，systemd 服务 `cvplatform.service`，
  Nginx 提供前端静态文件并把 `/api/` 反向代理到 `127.0.0.1:8000`。

## 目录

```text
CVPlatform/
├── backend/
│   ├── app/
│   │   ├── config.py          # 配置与数据库路径解析（开发/测试/生产）
│   │   ├── data/              # 版本化主题表 topics_v1.json（人工复核后可提交）
│   │   ├── db/                # 引擎、会话与版本化迁移（PRAGMA user_version）
│   │   ├── models/            # SQLModel 实体定义
│   │   ├── schemas/           # 请求与响应契约
│   │   ├── services/          # 论文、关键词、采集、导入、统计、主题归并、维护
│   │   │   └── sources/       # 外部来源：CVF Open Access / ECVA / OpenAlex
│   │   ├── routers/           # /api/papers、/api/collect、/api/import、/api/stats、/api/keywords
│   │   ├── harvest_cli.py     # 真实数据采集命令
│   │   ├── maintenance_cli.py # 状态、按需重算、主题重载、实体修复、独立复算
│   │   └── main.py            # 应用入口、统一错误响应、健康检查
│   ├── tests/                 # 独立临时数据库上的测试（不触碰开发与生产数据）
│   ├── requirements.txt       # 运行时依赖
│   └── requirements-dev.txt   # 开发与测试依赖（生产不装）
├── deploy/                    # 生产配置模板、备份脚本、升级与回退说明、可分发样例
├── frontend/
│   ├── src/
│   │   ├── api/               # HTTP 请求（health、paperApi、collectApi、importApi、statsApi）
│   │   ├── components/        # 可复用组件（含 ECharts 图谱与趋势曲线）
│   │   ├── composables/       # 组合式函数（ECharts 按需注册、年份轴、图表布局常量、GIF 合成与编码）
│   │   ├── layouts/           # 公共布局
│   │   ├── router/            # 六个页面路由与数据来源标记
│   │   ├── styles/            # 设计令牌与公共 UI 样式
│   │   ├── types/             # 领域类型（字段与后端契约一致）
│   │   └── views/             # 页面组件
│   └── package.json / package-lock.json
├── 数据覆盖与来源.md          # 数据侧事实：来源、抽样规则、覆盖、复现命令、缺口
└── codestyle.md               # 代码规范
```

## 页面入口

| 路径 | 页面 | 数据来源 |
|---|---|---|
| `/` | 热门方向总览 | 后端接口 `/api/stats/{summary,top,graph}`（ECharts 图谱） |
| `/trends` | 热度走势对比 | 后端接口 `/api/stats/{summary,trend,top}`（ECharts 曲线按年份逐段绘制 + 年度 Top 10 演变榜单，两个视图都可导出 GIF） |
| `/papers` | 论文管理 | 后端接口 `/api/papers`（主题下拉词表来自 `/api/stats/top`） |
| `/papers/:id` | 论文详情 | 后端接口 `/api/papers/{id}` |
| `/collect` | 采集与导入 | 后端接口 `/api/collect/*`、`/api/import/*` |
| `/about` | 关于平台 | 后端接口 `/api/stats/coverage` + 静态说明 |

数据边界：六个页面的数据全部来自后端接口，`frontend/src/demo/` 已随接入完成删除，
页面不再保留任何演示数值。范围与口径说明由 `/api/stats/coverage` 驱动（覆盖范围、数据性质、
规则版本、主题表规模都从接口取），缺失值显示为「—」「无记录」或「该届不举办」，不写成 0。

## 安装

在项目根目录执行（Windows PowerShell；当前开发机已完成安装，可直接跳到「启动」）：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt   # 仅开发与测试需要
npm --prefix frontend ci
```

Linux 服务器上把解释器路径换成 `.venv/bin/python`，其余命令相同。

## 配置

| 环境变量 | 作用 | 默认值 |
|---|---|---|
| `CVPLATFORM_ENV` | 运行环境：`development` / `test` / `production` | `development` |
| `CVPLATFORM_DB_PATH` | 直接指定数据库文件路径（优先级最高） | 见下 |
| `HARVEST_SAMPLE_LIMIT` | 每个会议年份的采集条数 | `200` |
| `IMPORT_MAX_ROWS` / `IMPORT_MAX_BYTES` | 批量导入的行数与文件大小上限 | `500` / `2 MB` |
| `STATS_DEFAULT_GROUP_BY` | 统计默认分组：`topic` / `keyword` | `topic` |

数据库路径解析顺序（`backend/app/config.py`）：

1. `CVPLATFORM_DB_PATH` 有值 → 直接使用；
2. `CVPLATFORM_ENV=production` → `/var/lib/cvplatform/cvplatform.db`；
3. `CVPLATFORM_ENV=test` → 系统临时目录下按进程唯一命名；
4. 其他（开发默认）→ `<仓库根>/data/cvplatform.db`（已被 `.gitignore` 忽略）。

开发默认路径锚定仓库根而不依赖启动时的工作目录，因此在任意目录启动都指向同一个数据库。
生产配置模板见 `deploy/env.example`，服务与权限说明见 `deploy/README.md`。
上表只列影响行为的主要开关；完整清单（出站请求的超时/重试/串行间隔、任务续跑开关
`AUTO_RESUME_TASKS`、由后端托管前端产物的 `CVPLATFORM_SERVE_FRONTEND`、数据集导入的年份下限
与摘要覆盖率阈值）见 `deploy/env.example`。

## 启动

在项目根目录打开两个终端。

```powershell
# 终端一：后端（开发用 --reload；生产由 systemd 启动，单 worker）
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

# 终端二：前端
npm --prefix frontend run dev
```

- 前端页面：<http://127.0.0.1:5173>
- 后端健康检查：<http://127.0.0.1:8000/api/health>
- 接口文档（Swagger UI）：<http://127.0.0.1:8000/docs>

前端通过相对路径请求 `/api`，Vite 在开发时把它代理到本地后端；部署时由 Nginx 承担这一层代理。

## 构建

```powershell
npm --prefix frontend run build          # 含 TypeScript 检查，产物在 frontend/dist
.\.venv\Scripts\python.exe -m pip check  # 依赖一致性检查
```

## 数据来源

| 来源 | 覆盖 | 字段 | 入口 |
|---|---|---|---|
| HuggingFace 会议论文集镜像 | 2020 年及以后的 CVPR / ICCV / ECCV | 题目、作者、摘要、原文链接、PDF | <https://huggingface.co/collections/ai-conferences/cvpr>（ICCV、ECCV 同格式） |
| CVF Open Access | CVPR、ICCV（单篇采集与抽样兜底） | 题目、作者、摘要、原文 PDF/落地页 | <https://openaccess.thecvf.com/> |
| ECVA | ECCV（单篇采集与抽样兜底） | 同上 | <https://www.ecva.net/papers.php> |
| OpenAlex | 在线兜底检索 | 题目、年份、DOI、摘要倒排索引、类型 | <https://openalex.org/> |

- **实测不可用**：DBLP 返回反爬页面（Anubis），带浏览器标识也被拦截，因此未接入；
  Semantic Scholar 公开接口在测试中触发限流，只作为可选说明保留。
- 采集规则：按会议年份索引页做确定性的等距抽样（步长 = 索引总数 ÷ 目标条数），
  每篇记录来源标识与获取时间，可逐条核对；外部请求带超时、限流与有限重试。
- **当前覆盖：13 个会议年份、29,072 篇**（2020 年及以后的 CVPR / ICCV / ECCV 完整论文集）：
  CVPR 2020—2026、ICCV 2021/2023/2025、ECCV 2020/2022/2024。数据集来自
  [ai-conferences](https://huggingface.co/ai-conferences) 的公开镜像，逐届一个数据集，
  每篇保留官方原文链接，导入时记录数据集修订号；`ECCV 2026` 因摘要覆盖率仅 64%（实测 63.7%，
  数据仍在补齐）被自动跳过。
- 2020 年以前以及数据集未覆盖的年份仍可用抽样采集（`harvest_cli --run`，每会议年份 200 篇）；
  逐组合的来源、样本量、摘要与关键词情况、去重与缺口见 [数据覆盖与来源.md](数据覆盖与来源.md)。

## 统计口径

所有统计只读两个 SQL 视图（`v_analysis_paper`、`v_analysis_keyword`），口径集中在这一处：

- **分母** = 分析集合的论文数：会议年份有效、标题可用、关键词已按当前规则版本处理完成；
  **关键词处理成功但结果为空仍计入**；
- **数据性质逐单元说明**：完整论文集覆盖的会议年份（2020 年及以后）占比就是该届录用论文中的比例；
  抽样年份（每组合最多 200 篇）只表示样本内相对热度。接口用 `coverage.coverage_kinds` 与
  `coverage.full_coverage_years` 区分，界面据此分述，不用一句「抽样」概括全部数据；
- **只统计系统提取的关键词**；作者关键词只做展示，不参与榜单、图谱与趋势；
- **去重**：同一篇论文对同一主题只计一次；跨会议年份汇总时先合并计数与分母，再相除；
- **「没有数据」分三种，零是第四种**（都会在接口的 `reason` 上分开）：
  ①「该届不举办」（ICCV 偶数年、ECCV 奇数年）→ `not_a_conference_year`，曲线跨过该年份连线；
  ②「该届存在但按完整度策略跳过」（如 ECCV 2026 摘要覆盖率仅 64%）→ `out_of_scope`，
  不画缺口标注，也不当作缺失；
  ③「范围内该届没采到数据」→ `no_records_in_sample`，曲线断开并标注灰色区间；
  ④ 有样本但该主题 0 篇 → `count = 0`（落在 0 轴）。
  四者画法不同，避免把「没举办」「范围外」「没采到」「热度为 0」混为一谈；
- 被排除的论文（待处理 / 失败 / 旧规则版本 / 标题不可用）在响应的 `excluded` 字段单列，四个计数互斥。

主题归并层：关键词 → 主题（`topic` + `topic_alias`，版本化文件 `backend/app/data/topics_v1.json`）。
归并只影响统计展示，详情页始终展示系统抽到的原始关键词；映射不到的关键词如实标为「未归类」，
其数量在界面说明中给出。

从总览页或趋势页跳到论文列表时会带 `from_stats=true`，后端据此强制应用同一套口径
（只算系统关键词、只认当前规则版本、限制在分析集合内），使**列表条数与统计计数一致**。

## 接口与复现入口

| 入口 | 说明 |
|---|---|
| `GET /api/health` | 健康检查（含数据库路径与结构版本） |
| `GET /api/papers`、`/api/papers/{id}` | 论文检索（分页、排序、精确/模糊、组合筛选）与增删改查 |
| `POST /api/collect/lookup`、`/api/collect/confirm` | 单篇采集与候选确认 |
| `POST /api/import/preview`、`/api/import/tasks` | 批量导入预览与任务（TXT/CSV、重试、重启续跑） |
| `GET /api/stats/summary`、`/top`、`/graph`、`/trend`、`/coverage` | 概览、榜单、图谱、趋势、覆盖明细 |
| `GET /api/keywords/status`、`POST /api/keywords/process`、`POST /api/keywords/topics/reload` | 关键词处理现状、按需处理、主题表重载 |

命令行入口（在仓库根目录，先设 `PYTHONPATH=backend`）：

```powershell
$env:PYTHONPATH = "backend"
# 真实数据采集：--plan 只打印抽样计划；--run 创建任务并处理；中断后重跑即可续做
.\.venv\Scripts\python.exe -m app.harvest_cli --plan
.\.venv\Scripts\python.exe -m app.harvest_cli --run
# 导入 2020 年及以后的完整论文集（纳入前校验摘要覆盖率，自动跳过不完整年份）
.\.venv\Scripts\python.exe -m app.harvest_cli --datasets
# 关键词与统计维护
.\.venv\Scripts\python.exe -m app.maintenance_cli status
.\.venv\Scripts\python.exe -m app.maintenance_cli process-keywords --force
.\.venv\Scripts\python.exe -m app.maintenance_cli reload-topics
.\.venv\Scripts\python.exe -m app.maintenance_cli fix-entities --apply
# 导入课程数据集或可分发样例（JSON），复用同一套清洗、去重与关键词逻辑
.\.venv\Scripts\python.exe -m app.maintenance_cli import-dataset deploy/sample/cvplatform_sample.json
# 用独立写的 SQL 复算统计结果，并测量接口耗时与内存峰值
.\.venv\Scripts\python.exe -m app.maintenance_cli verify-stats
```

从空库复现完整流程（约 20 分钟，取决于网络）：

```powershell
$env:CVPLATFORM_DB_PATH = "$PWD\data\acceptance\cvplatform.db"   # 独立数据库，不影响开发库
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -c "from app.db.engine import init_database; print(init_database())"
.\.venv\Scripts\python.exe -m app.harvest_cli --run              # 采集 6 个会议年份各 200 篇
.\.venv\Scripts\python.exe -m app.maintenance_cli reload-topics  # 载入主题表并映射关键词
.\.venv\Scripts\python.exe -m app.maintenance_cli verify-stats   # 独立复算统计结果
```

也可用可分发样例（10 条真实记录，见 `deploy/sample/`）快速验证导入链路：

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m app.maintenance_cli import-dataset deploy/sample/cvplatform_sample.json
```

## 测试与验证

```powershell
# 后端：使用独立临时数据库，不触碰开发与生产数据
.\.venv\Scripts\python.exe -m pytest backend\tests -q
# 前端：类型检查 + 生产构建
npm --prefix frontend run build
```

测试覆盖数据模型与迁移、CRUD 与检索、错误契约、采集与候选确认、批量导入的任务生命周期、
关键词规则与校准、统计口径（可手算数据集）、主题归并与维护、统计页跳转列表的口径一致性。
**前端没有单元测试**：组件、图表与动画的正确性靠类型检查、生产构建与浏览器实测把关
（动画与 GIF 导出在浏览器里量过播放头位移、逐帧曲线像素与解码后的帧数，见提交说明）。

## 部署

完整操作手册见 **[deploy/README.md](deploy/README.md)**（服务器现状、更新与回退命令、
数据库替换与重采两种做法、2 核/2GB 下的参数、线上验收清单）。本目录提供的文件：

| 文件 | 用途 |
|---|---|
| `deploy/README.md` | 部署与更新手册（含本轮实测的线上状态与遗留） |
| `deploy/update.sh` | 服务端更新脚本：预检查 → 备份 → 替换 → 装依赖 → 迁移 → 重启 → 冒烟检查，支持 `--dry-run` |
| `deploy/smoke_check.sh` | 只读冒烟检查：接口、错误契约、口径一致性、子路由与静态资源 |
| `deploy/make_release.sh` | 在本机打包发布产物（`bash deploy/make_release.sh 1.0.0 [--with-db]`） |
| `deploy/cvplatform.service.example` | systemd 单元模板（单 worker、只监听 127.0.0.1） |
| `deploy/user/{bootstrap,install,ctl}.sh` | 无 sudo / 无 systemd / 无 Nginx 的机器上的一键部署（代码与数据放在家目录，后端托管前端）；`bootstrap.sh` 会自动探测环境、按需装 Python 3.12、并处理 80 端口的绑定授权 |
| `deploy/nginx.conf.example` | Nginx 站点模板（静态目录、`/api/` 代理、history 回退、HTTPS 段） |
| `deploy/env.example` | 环境变量模板（只列代码真正读取的开关） |
| `deploy/backup_database.py` | SQLite 在线备份（WAL 下也一致，不用停服务） |

发布包在本机生成（`data/release/` 下，已被 Git 忽略，不入库），上传后按手册执行即可。

**当前线上状态（2026-09-23 更新）**：<http://123.249.79.118> 已部署通过本地验收的业务版本——
13 个会议年份、29,072 篇真实论文，统计/图谱/趋势均可用；HTTPS 待域名备案后配置。
本轮实际部署结果、人工执行时踩到的问题与修复见 `deploy/README.md` 第 11 节。
**线上版本落后于仓库最新提交**：热度走势的动画细化与「导出 GIF」尚未同步到线上，
按第 4 节更新（`git checkout 1.0.0`）即可，数据与接口契约没有变化。

```bash
# 服务器上（Ubuntu 24.04）
sudo -u cvplatform git clone <CodeArts 仓库地址> /opt/cvplatform
sudo -u cvplatform python3.12 -m venv /opt/cvplatform/.venv
sudo -u cvplatform /opt/cvplatform/.venv/bin/pip install -r /opt/cvplatform/backend/requirements.txt
npm --prefix /opt/cvplatform/frontend ci && npm --prefix /opt/cvplatform/frontend run build
sudo systemctl restart cvplatform.service      # 启动时自动执行未应用的迁移
```

升级前先备份（`deploy/backup_database.py` 走 SQLite 在线备份接口，WAL 下也一致），
升级后按 `deploy/README.md` 的冒烟检查逐条确认。



## AI 使用说明

本项目在 AI 编程助手（ZCode）辅助下按阶段实现，每个阶段都有明确的人工复核环节：

- **人的决策**：技术选型与取舍（SQLite、单 worker、不引入向量化依赖）、统计口径（分析集合与分母、
  缺失与零的区分、未归类不参与排序）、主题归并方案、抽样范围与验收标准，以及每阶段的接受或退回
  ——阶段 3、6 曾被退回并要求修正具体问题后才继续。
- **AI 的实现**：按阶段提示词编写后端与前端代码、测试与文档草稿，并在每阶段执行测试、类型检查、
  构建与浏览器验证；对设计文档中不适合本项目的建议（如短语互信息阈值）给出实测数据并说明未采用的理由。
- **可核对的记录**：进展、决策与遗留问题记在 `开发设计与验收.md`（本地工作文档，按约定不入库），
  数据侧事实记在 [数据覆盖与来源.md](数据覆盖与来源.md)，提交说明见 CodeArts 提交历史。
- 代码规范见 `codestyle.md`；所有 AI 生成的代码均由人工复核后提交。

## 已知限制

- **数据集未覆盖的年份仍是抽样**（`harvest_cli --run`，每会议年份 200 篇）：这些年份的占比只表示
  样本内的相对热度，不等于整届大会的录用比例。2020 年及以后的 13 个会议年份是完整论文集，
  占比即该届录用论文中的比例——接口用 `coverage.coverage_kinds` 与 `full_coverage_years` 区分，
  界面对这两类数据分述，不用一句「抽样」概括全部；
- 趋势曲线按会议年份取值：ICCV 只有奇数年、ECCV 只有偶数年，单条曲线的相邻点在时间上相隔两年。
  「该届不举办」跨过连线、「范围内没采到数据」断开并标注灰区，两者都不是「热度为 0」；
- 关键词规则版本升级后，旧版本处理过的论文需要重跑（`maintenance_cli process-keywords --force`）；
  重跑完成前这些论文不进分析分母，界面上单列为「待处理」，不与「失败」混计；
- 未归类关键词数量较大（长尾），只在界面说明中给出数量，未单独出图；
- 域名与 HTTPS 尚未配置（当前用公网 IP 联调；域名与备案确定后按 `deploy/nginx.conf.example` 启用）；
- 前端没有单元测试：组件、图表与动画靠类型检查、生产构建与浏览器实测核对（后端有 243 个测试）。
