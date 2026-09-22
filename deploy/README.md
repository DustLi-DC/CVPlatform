# CVPlatform 服务器部署与更新手册

本目录保存服务器侧配置的**脱敏模板**与**可执行脚本**，不含任何真实密钥或凭据。
本文件是更新线上环境时的操作手册：每一步都可以直接复制执行，命令里的路径与运行用户都已按
当前服务器实际情况填写。

## 1. 服务器现状（实际核对）

| 项目 | 实际值 | 来源 |
|---|---|---|
| 系统 | 华为云 Ubuntu 24.04，2 核 / 2GB / 2Mbps | 用户提供 |
| 代码目录 | `/opt/cvplatform` | 用户提供 |
| 服务单元 | `cvplatform.service` | 用户提供 |
| 运行用户 | `cvplatform`（不可登录） | 用户提供 |
| 后端监听 | `127.0.0.1:8000`，单 worker | 用户提供 |
| 数据库 | `/var/lib/cvplatform/cvplatform.db` | 本仓库配置（`config.py`） |
| 数据目录权限 | `cvplatform` 可写（WAL 需目录写权限） | 见第 3 节校验命令 |
| Nginx | 1.24.0 (Ubuntu)，静态前端 + `/api/` 代理 | 本轮 `curl -sSI` 实测 |
| 公网入口 | <http://123.249.79.118>（HTTP 200，健康检查通过） | 本轮实测 |
| HTTPS | **未配置**（`https://123.249.79.118` 连接被重置） | 本轮实测；域名尚未备案，备案后再配证书 |
| 域名 | **暂不使用**（人工确认：尚未备案，先用 IP） | 人工 |

**只存在于服务器、未纳入版本管理的配置**已在本目录补上脱敏模板：

| 服务器文件 | 模板 | 说明 |
|---|---|---|
| `/etc/systemd/system/cvplatform.service` | `cvplatform.service.example` | 单 worker、只监听本机、内存上限 800M |
| `/etc/nginx/sites-available/cvplatform` | `nginx.conf.example` | 静态目录、`/api/` 代理、history 模式回退 |
| `/etc/cvplatform.env` | `env.example` | 环境变量（权限 0640，属主 root:cvplatform） |

> 本轮**未能直接登录服务器核对**：本机 `~/.ssh` 已有密钥、`known_hosts` 也含该 IP，
> 但用 `ssh -o BatchMode=yes` 以 `root` 与 `cvplatform` 尝试均返回
> `Permission denied (publickey,password)`——说明服务器上没有授权本机公钥。
> 因此第 4–7 节的命令需要由**有权限的人工**在服务器上执行，或先为本机公钥授权后我再执行。

## 2. 发布包里有什么

发布包由本机构建，只含运行所需内容（不含 `.venv`、`node_modules`、测试与本地工作文档）：

```text
cvplatform-release-1.0.0/
├── backend/                 # 后端源码（app/、tests/ 按需，运行时只需 app/）
│   └── app/data/topics_v1.json   # 版本化主题表（运行时必需）
├── frontend/dist/           # 本机构建的前端产物（index.html + assets/）
├── deploy/                  # 本脚本与模板（update.sh、smoke_check.sh、backup_database.py）
├── requirements.txt         # 生产依赖（不含 dev）
├── README.md  数据覆盖与来源.md  codestyle.md
└── data/cvplatform.db       # 可选：随包发布的生产数据库（见第 5 节，需要 --with-db）
```

生成方式（在仓库根目录执行，需已 `npm ci`）：

```bash
npm --prefix frontend run build
.venv/Scripts/python.exe -m pip check
# 打包脚本：bash deploy/make_release.sh 1.0.0 [--with-db]
```

## 3. 首次部署或数据目录校验

若 `/var/lib/cvplatform` 还不存在，或不确定 `cvplatform` 用户能否写入（WAL 需要**目录**写权限）：

```bash
sudo install -d -o cvplatform -g cvplatform -m 0750 /var/lib/cvplatform
sudo install -d -o cvplatform -g cvplatform -m 0750 /var/lib/cvplatform/backups
# 以运行用户身份实际写入，并确认 WAL 可用
sudo -u cvplatform test -w /var/lib/cvplatform && echo "目录可写"
sudo -u cvplatform /opt/cvplatform/.venv/bin/python -c "
import sqlite3
c = sqlite3.connect('/var/lib/cvplatform/cvplatform.db')
print('journal_mode =', c.execute('PRAGMA journal_mode=WAL').fetchone()[0])
c.execute('CREATE TABLE IF NOT EXISTS _writeprobe(x int)')
c.execute('INSERT INTO _writeprobe VALUES (1)')
c.execute('DROP TABLE _writeprobe')
c.commit(); c.close()
print('运行用户写入与 WAL 均正常')
"
```

## 4. 更新线上（推荐路径：git）

服务器上已是 git 检出时，用 git 更新最省事（`update.sh` 也支持发布包，见第 6 节）：

```bash
# 0) 先备份，再拉代码：备份脚本走 SQLite 在线备份接口，WAL 下也一致，不用停服务
sudo -u cvplatform /opt/cvplatform/.venv/bin/python /opt/cvplatform/deploy/backup_database.py

# 1) 拉取指定版本（用提交号或标签，保证可复现；不要直接跟 master 漂移）
cd /opt/cvplatform
sudo -u cvplatform git fetch --all --tags
sudo -u cvplatform git checkout 1.0.0        # 或具体提交号

# 2) 更新后端依赖（生产只装 requirements.txt）
sudo -u cvplatform /opt/cvplatform/.venv/bin/pip install -r backend/requirements.txt

# 3) 在本机（开发机）构建前端后同步产物，或在服务器上直接构建（需要 Node）：
npm --prefix frontend ci && npm --prefix frontend run build

# 4) 显式跑一次迁移（启动时也会自动执行；先单独跑便于看到结果与自动备份）
sudo -u cvplatform env CVPLATFORM_ENV=production CVPLATFORM_DB_PATH=/var/lib/cvplatform/cvplatform.db \
  PYTHONPATH=/opt/cvplatform/backend \
  /opt/cvplatform/.venv/bin/python -c "from app.db.engine import init_database; print(init_database())"

# 5) 重启服务
sudo systemctl restart cvplatform.service
sudo systemctl status cvplatform.service --no-pager

# 6) 冒烟检查（只读，不改数据）
bash /opt/cvplatform/deploy/smoke_check.sh
bash /opt/cvplatform/deploy/smoke_check.sh http://123.249.79.118   # 同时检查公网入口
```

数据库结构升级由应用启动时的 `initialize_database()` 按 `PRAGMA user_version` 判断，
**只应用尚未应用的迁移**；需要变更结构时会自动再做一次在线备份（`reason=v<旧版本>`）。

## 5. 数据库：保留旧数据，或换成随包的完整数据

两种做法都先备份，按需要选一种：

**A. 保留服务器现有数据库（默认）**：不额外操作，代码替换后数据仍在 `/var/lib/cvplatform`。
若服务器上还没有数据，站点会是空库状态（各页面显示「暂无数据 / 分母 0」，这是如实呈现）。

**B. 用发布包里的数据库替换（本次推荐，站点立即有 13 个会议年份、29,072 篇真实数据）**：

```bash
# 1) 先备份现有库（务必先做）
sudo -u cvplatform /opt/cvplatform/.venv/bin/python /opt/cvplatform/deploy/backup_database.py
# 2) 停服务后替换（避免替换过程中有写入）
sudo systemctl stop cvplatform.service
sudo -u cvplatform cp /tmp/cvplatform-release-1.0.0/data/cvplatform.db /var/lib/cvplatform/cvplatform.db
sudo rm -f /var/lib/cvplatform/cvplatform.db-wal /var/lib/cvplatform/cvplatform.db-shm
sudo chown cvplatform:cvplatform /var/lib/cvplatform/cvplatform.db
sudo systemctl start cvplatform.service
bash /opt/cvplatform/deploy/smoke_check.sh
# 3) 核对口径与数据量（应与随包数据一致：分母 29072、13 个会议年份）
curl -s http://127.0.0.1:8000/api/stats/coverage | head -c 400
```

**C. 让服务器自己重新采集数据集**（不在服务器装 pyarrow 也可以，JSON 分页回落到较慢）：
需要服务器能访问 HuggingFace，且耗时约 6 分钟（下载）+ 9 分钟（关键词重算）：

```bash
sudo -u cvplatform env CVPLATFORM_ENV=production PYTHONPATH=/opt/cvplatform/backend \
  /opt/cvplatform/.venv/bin/python -m app.harvest_cli --datasets
sudo -u cvplatform env CVPLATFORM_ENV=production PYTHONPATH=/opt/cvplatform/backend \
  /opt/cvplatform/.venv/bin/python -m app.maintenance_cli process-keywords --force
sudo -u cvplatform env CVPLATFORM_ENV=production PYTHONPATH=/opt/cvplatform/backend \
  /opt/cvplatform/.venv/bin/python -m app.maintenance_cli reload-topics
```

## 6. 更新线上（备用路径：发布包脚本）

无法用 git 时，把发布包上传到服务器后：

```bash
sudo mkdir -p /tmp/cvplatform-release-1.0.0
sudo tar -xzf cvplatform-release-1.0.0.tar.gz -C /tmp/cvplatform-release-1.0.0
sudo bash /tmp/cvplatform-release-1.0.0/deploy/update.sh --release /tmp/cvplatform-release-1.0.0 --dry-run
sudo bash /tmp/cvplatform-release-1.0.0/deploy/update.sh --release /tmp/cvplatform-release-1.0.0 --with-db
```

`update.sh` 的顺序是：预检查 → 备份（数据库在线备份 + 代码与前端产物打包）→ 替换代码与产物 →
装依赖 → 跑迁移（可选替换数据库）→ 重启服务 → 冒烟检查；任何一步失败即停止并打印回退命令。

## 7. 回退

```bash
# 代码与前端产物
sudo tar -xzf /var/lib/cvplatform/backups/app-<时间戳>.tar.gz -C /opt/cvplatform
sudo systemctl restart cvplatform.service

# 数据库（选择升级前的那一份备份）
ls -lt /var/lib/cvplatform/backups/
sudo systemctl stop cvplatform.service
sudo -u cvplatform cp /var/lib/cvplatform/backups/cvplatform-<升级前时间戳>.db /var/lib/cvplatform/cvplatform.db
sudo rm -f /var/lib/cvplatform/cvplatform.db-wal /var/lib/cvplatform/cvplatform.db-shm
sudo chown cvplatform:cvplatform /var/lib/cvplatform/cvplatform.db
sudo systemctl start cvplatform.service
bash /opt/cvplatform/deploy/smoke_check.sh
```

结构升级与代码回退要**成对**执行：代码回到旧版本时，数据库也应回到升级前的备份（旧代码不认识新列，
但 SQLite 的「只增列不删列」策略下旧代码通常仍能运行；对称回退最稳妥）。

## 8. 资源约束下的参数（2 核 / 2GB / 2Mbps）

| 项 | 取值 | 说明 |
|---|---|---|
| 后端 worker | 1 | 多 worker 会让后台任务重复领取、放大 SQLite 写锁竞争 |
| 出站请求 | 间隔 0.5s、串行、超时 10s、重试 2 次 | 见 `env.example`；遇 429/403 会自动退避（上限 10s） |
| 关键词处理 | 每 200 篇提交一次 | 批量导入/重算时可中断续跑，WAL 不会无界增长 |
| 统计缓存 | 进程内 64 条，按分析集合版本失效 | 冷启动约 1.4–2.2 秒（2.9 万篇），缓存命中 <1ms |
| 图谱默认节点 | 40，可选 20/60/100 | 节点上限 200 时内存峰值约 25MB |
| 服务内存上限 | `MemoryMax=800M` | 见服务模板，防止异常时拖死整机 |

批量处理期间建议观察：

```bash
top -b -n1 | head -12                 # CPU 与内存
systemctl show cvplatform.service -p MemoryCurrent
curl -s -o /dev/null -w '%{time_total}s\n' http://127.0.0.1:8000/api/stats/summary   # 接口响应
```

## 9. 线上验收清单（执行后请回传结果）

| 检查 | 命令 | 期望 |
|---|---|---|
| 服务与端口 | `systemctl is-active cvplatform.service` / `ss -ltnp \| grep 8000` | `active`；只在 `127.0.0.1:8000` 监听 |
| 健康检查 | `curl -s http://127.0.0.1:8000/api/health` | `{"status":"ok",...}` |
| 接口清单 | `curl -s http://127.0.0.1:8000/openapi.json \| grep -c '"\/api\/stats\/coverage"'` | `1`（确认是新版本） |
| 数据口径 | `curl -s http://127.0.0.1:8000/api/stats/coverage` | 13 个会议年份、29072 篇，`coverage_kinds.full=13` |
| 公网入口 | `curl -sI http://<域名或IP>/` | `200`，引用本机构建的 `assets/index-*.js` |
| 子路由刷新 | `curl -sI http://<域名或IP>/trends` | `200`（history 模式回退生效，不是 404） |
| 接口代理 | `curl -s http://<域名或IP>/api/health` | 同上，经 Nginx 代理 |
| 运行用户写入 | 第 3 节的写入探针 | 「运行用户写入与 WAL 均正常」 |
| 重启持久化 | `sudo systemctl restart cvplatform.service` 后再查论文数与分母 | 数值不变 |
| 前端构建一致性 | `curl -s http://<域名或IP>/ \| grep -o 'assets/[^"]*'` 与 `ls frontend/dist/assets` | 文件名完全一致 |
| HTTPS | `curl -k -sI https://<域名>/` | 有证书时 200；当前无证书，预期连接失败 |
| 冒烟脚本 | `bash /opt/cvplatform/deploy/smoke_check.sh http://<域名或IP>` | 「全部通过」 |
| **云端数据源可达** | `for u in https://openaccess.thecvf.com/ https://www.ecva.net/papers.php https://api.openalex.org/works?per_page=1 https://datasets-server.huggingface.co/info; do curl -sI -m 15 "$u" \| head -1; done` | 单篇采集与在线兜底依赖这四个出站地址；若被安全组或代理拦截，采集与「未命中联网检索」会退化为「来源不可用」 |
| 采集链路端到端 | 在 `/collect` 用库中不存在的题目检索一次 | 返回候选列表或如实报「联网未找到 / 来源不可用」；HTTP 必须是 200 或 502/504（业务结局），不能是 500 |

## 11. 本轮实际部署记录（2026-09-23）

线上已从阶段 2 的骨架版本更新到通过本地验收的业务版本。

| 项 | 实际结果 |
|---|---|
| 更新方式 | 发布包 + `deploy/update.sh --with-db`（人工在服务器执行，本机无 SSH 权限） |
| 代码与前端 | `/opt/cvplatform/backend`、`/opt/cvplatform/frontend/dist` 已替换；首页引用 `assets/index-DoO3myXm.js`，与本机构建**逐字节一致**（文件名即内容哈希） |
| 依赖 | 全部 `Requirement already satisfied`（本轮无新增运行时依赖；pyarrow 只在批量导入时按需导入） |
| 数据库 | `/var/lib/cvplatform/cvplatform.db`，用随包快照替换（替换前已备份）；结构 v1，`PRAGMA integrity_check=ok` |
| 服务环境 | **原本缺少生产环境变量**，导致启动时报 `PermissionError: '/opt/cvplatform/data'`；新增 `deploy/setup_service_env.sh` 用 systemd drop-in 补上 `EnvironmentFile=/etc/cvplatform.env`，服务恢复 active |
| 线上数据 | 分母 29,072、13 个会议年份（`coverage_kinds.full=13`）、规则 kw-v4、主题表 topic-v3（40 主题 / 807 别名）；来源分布 huggingface 29,069 + cvf 800 + ecva 400 |
| 口径一致性 | 榜首主题「三维重建与辐射场」统计 7,546 篇 = 带统计口径的列表 7,546 条 |
| 页面 | `/`、`/trends`、`/papers`、`/about`、`/collect` 均 200；未知路径经 history 回退也返回 200 |
| 接口 | 健康检查、概览、榜单、图谱、趋势、关键词状态、论文列表全部 200 |
| 公网响应时间 | 概览 0.13s、榜单 0.13s、图谱 0.19s、趋势 0.15s（进程内缓存命中） |
| 云端出站 | `/api/collect/lookup` 用库外的题名「Deep Residual Learning…」→ `remote_candidates`，OpenAlex 返回 5 个候选（3.5 秒） |
| CRUD | 新增 201（编号 `CVPR-2024-2717`）→ 详情 200 → 编辑 200 → 删除 204 → 再查 404 `paper_not_found`；记录数 29072→29073→29072 |
| 批量任务 | 预览 200 不写库 → 建任务 202（task 10）→ 终态「成功 0、重复 2、失败 0」并逐条标出现有编号 → 记录数不变 |
| 重启持久化 | 服务重启后数据与分母不变（数据库在 `/var/lib/cvplatform`，与代码目录分离） |

**副作用（如实记录）**：CRUD 探针占用编号 `CVPR-2024-2717`（编号按设计不复用，探针记录已删除）；批量任务占用 task id 10。

**仍未验证**：域名与 HTTPS（域名未备案，先用 IP）；批量处理期间的 CPU/内存实测需要服务器侧命令
（建议在导入任务运行时执行 `systemctl show cvplatform.service -p MemoryCurrent` 与 `uptime`）。

**人工执行时踩到的问题与修复（已回灌到脚本）**：CRLF 行尾导致脚本无法执行（新增行尾归一化与自愈头）；
服务存在性检查方式不可靠（改用 `systemctl cat`）；`/opt/cvplatform/deploy` 名称异常时中止更新（改为跳过并说明）；
pip 以 cvplatform 身份装不进 root 属主的 venv（改为按 venv 属主选择身份）；重启前未校验服务是否指向生产库
（新增启动前拦截与 `setup_service_env.sh`）。

## 11b. 用户级部署（无 sudo / 无 systemd / 无 Nginx）

适用于只能以普通用户登录的机器（例如 `ssh WORK2@65.52.167.95`；该机对本机不可直连，
`10.1.1.4` 属内网亦不可达，因此以下步骤由人工执行）。与前面 systemd 方案的区别：

| 项 | systemd 方案 | 用户级方案 |
|---|---|---|
| 运行身份 | 服务用户 `cvplatform` | 登录用户自己（如 `WORK2`） |
| 代码 / 数据 | `/opt/cvplatform`、`/var/lib/cvplatform` | `~/cvplatform`、`~/cvplatform-data` |
| 进程管理 | `systemctl` | `deploy/user/ctl.sh`（nohup + PID 文件） |
| 前端托管 | Nginx 静态目录 | **由后端自己托管**（`CVPLATFORM_SERVE_FRONTEND`），单进程同时提供页面与接口 |
| 需要 root | 是 | 否 |

后端托管前端的实现要点（`app/main.py` 的 `_mount_frontend`）：`/assets/**` 走 StaticFiles，
其余非 API 路径回退 `index.html`（Vue Router history 模式刷新不掉 404），
而 `/api/**`、`/docs`、`/openapi.json` **仍走框架自身路由与 JSON 404 语义**——接口打错路径不会拿到 HTML。

步骤：

```bash
# 开发机：打包并上传（发布包在 data/release/ 下）
bash deploy/make_release.sh 1.0.0 --with-db
scp data/release/cvplatform-release-1.0.0.tar.gz WORK2@65.52.167.95:/tmp/

# 服务器：解包并安装（自动化程度最高的一步：建目录 → 建 venv → 装依赖 → 部署代码与前端
#         → 放置数据库快照 → 写 env.sh → 启动 → 自检）
cd ~ && tar -xzf /tmp/cvplatform-release-1.0.0.tar.gz
bash ~/cvplatform-release-1.0.0/deploy/user/install.sh ~/cvplatform-release-1.0.0 --port 8000

# 日常操作
bash ~/cvplatform/deploy/user/ctl.sh status|logs|restart|stop
```

可调项：`--port`（默认 8000，被占用时换一个）、`--no-db`（保留现有数据库）、
`CVPLATFORM_SKIP_DEPS=1`（依赖已装过时跳过 pip）。

对外访问需要放行端口；若机器不对公网开放，用 SSH 端口转发即可：
`ssh -L 8080:127.0.0.1:8000 WORK2@65.52.167.95`，再在本地打开 `http://127.0.0.1:8080`。

## 12. 本轮遗留

- **无 SSH 权限**：本机公钥未授权到服务器，第 4–7 节需要人工执行，或授权后由我执行；
- **无域名与证书**：HTTPS 未配置，`server_name` 暂用 IP，待域名提供后按 `nginx.conf.example` 的
  HTTPS 段启用并验证；
- `KEYWORD_VERSION_KEEP`（旧规则版本清理份数）在设计文档里提到，但**代码尚未实现**，
  已从 `env.example` 移除，避免出现「改了却不生效」的配置项；
- 首次更新时服务器上的 `cvplatform.service` 缺少生产环境变量，已由 `setup_service_env.sh`
  以 drop-in 方式补齐（未改动原单元文件）；后续重装系统或重建服务时需再执行一次该脚本。
