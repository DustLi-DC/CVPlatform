# 部署配置增量（阶段 3）

本目录保存服务器侧配置的**增量与说明**，不包含任何真实密钥。现有服务基线见 `../README.md` 与
`../实施基线.md`（后者为本地工作文档）；本文件记录阶段 3 新增的数据库相关配置，供阶段 11 更新线上时使用。

## 1. 生产数据目录与权限

数据库不再放在代码目录，而是独立到 `/var/lib/cvplatform`，这样**更新代码不会影响数据**。

| 项目 | 值 |
|---|---|
| 数据目录 | `/var/lib/cvplatform` |
| 数据库文件 | `/var/lib/cvplatform/cvplatform.db` |
| 备份目录 | `/var/lib/cvplatform/backups` |
| 运行用户 / 组 | `cvplatform` / `cvplatform` |
| 后端监听 | `127.0.0.1:8000`（单 worker） |

创建与授权（在服务器上以 root 执行）：

```bash
sudo install -d -o cvplatform -g cvplatform -m 0750 /var/lib/cvplatform
sudo install -d -o cvplatform -g cvplatform -m 0750 /var/lib/cvplatform/backups
```

**为什么必须是 `cvplatform` 用户可写整个目录，而不只是数据库文件**：SQLite 启用 WAL 后会在同目录
创建 `cvplatform.db-wal` 与 `cvplatform.db-shm` 两个临时文件，写入时需要**目录写权限**。只给数据库
文件写权限无法工作。

校验（以运行用户身份实际写入，不只检查属主）：

```bash
sudo -u cvplatform test -w /var/lib/cvplatform && echo "目录可写"
sudo -u cvplatform python3 -c "
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

> 阶段 3 不接触服务器，因此上述命令**尚未在线上执行**；按任务要求，线上运行用户写入验证在阶段 11
> 实际发布时执行并记录结果。

## 2. systemd 环境变量

服务单元需要读取 `/etc/cvplatform.env`（模板见 `env.example`）：

```ini
# /etc/systemd/system/cvplatform.service 的 [Service] 段增加
EnvironmentFile=/etc/cvplatform.env
```

安装环境文件并保持最小可读权限：

```bash
sudo install -o root -g cvplatform -m 0640 deploy/env.example /etc/cvplatform.env
sudo editor /etc/cvplatform.env      # 按实际填写，至少确认 CVPLATFORM_ENV 与 CVPLATFORM_DB_PATH
sudo systemctl daemon-reload
sudo systemctl restart cvplatform
```

启动日志会打印实际使用的数据库路径、环境与结构版本，可用来确认配置生效：

```bash
journalctl -u cvplatform -n 20 | grep 数据库就绪
```

## 3. 数据库路径解析规则

由 `backend/app/config.py` 统一决定，优先级从高到低：

1. 环境变量 `CVPLATFORM_DB_PATH` 有值 → 直接使用；
2. `CVPLATFORM_ENV=production` → `/var/lib/cvplatform/cvplatform.db`；
3. `CVPLATFORM_ENV=test` → 系统临时目录下按进程唯一命名（测试用，互不干扰）；
4. 其他（开发默认） → `<仓库根>/data/cvplatform.db`，该目录已加入 `.gitignore`。

**路径锚定仓库根而不是启动时的工作目录**，因此在任意目录启动服务，开发环境都指向同一个数据库文件。

## 4. 备份

统一使用 SQLite 在线备份接口，不需要停服务：

```bash
python3 deploy/backup_database.py /var/lib/cvplatform/cvplatform.db /var/lib/cvplatform/backups
```

不传第二个参数时，备份目录默认为**数据库同级的 `backups/` 子目录**（即 `/var/lib/cvplatform/backups`），也可用 `CVPLATFORM_BACKUP_DIR` 覆盖。脚本会备份、做 `PRAGMA integrity_check` 校验，并保留最近 10 份；清理只针对**本脚本为同一个数据库生成的** `{库名}-时间戳.db` 文件，不会触碰同目录下的其他数据库或文件。

**不要直接 `cp cvplatform.db`**：WAL 模式下已提交的数据可能还在 `cvplatform.db-wal` 里，复制主文件会
拿到不完整或落后的数据。备份必须走 `Connection.backup()`（脚本已封装）。

结构迁移执行前，应用自身也会自动留一份备份（文件名带 `bak-v<旧版本>-<时间戳>`），因此升级失败可以回退。

## 5. 结构升级（保留数据）

```bash
# 1) 升级前手动备份一次（双保险）
python3 deploy/backup_database.py /var/lib/cvplatform/cvplatform.db

# 2) 部署新代码并重启，启动时自动执行未应用的迁移
sudo systemctl restart cvplatform
journalctl -u cvplatform -n 20 | grep 数据库就绪   # 确认 结构版本 vN → vN+1

# 3) 冒烟检查
curl -s http://127.0.0.1:8000/api/health
curl -s "http://127.0.0.1:8000/api/papers?page_size=1" | head -c 200
```

迁移规则（见 `backend/app/db/migrations.py`）：

- 版本号载体为 SQLite 的 `PRAGMA user_version`，按 version 升序逐级执行，每步只执行一次；
- 语句写成幂等（`IF NOT EXISTS`，改列前先查 `PRAGMA table_info`），重复执行不会报错；
- **只增列、不删列、不改列类型**；需要改语义时新增列并回填，旧列保留；
- 迁移只改结构。数据级演进（换关键词规则版本）不重建表，而是把受影响论文的
  `keyword_status` 置回 `pending`，由后台任务增量重算，期间旧结果仍可查询但不计入当前版本统计。

当前结构版本：**v1（initial_schema）**。

## 6. 回退

```bash
# 1) 停止服务
sudo systemctl stop cvplatform

# 2) 用备份还原数据库（选择升级前的备份，或 bak-v<version> 文件）
sudo -u cvplatform cp /var/lib/cvplatform/backups/cvplatform-<时间戳>.db \
                       /var/lib/cvplatform/cvplatform.db
sudo -u cvplatform rm -f /var/lib/cvplatform/cvplatform.db-wal \
                         /var/lib/cvplatform/cvplatform.db-shm

# 3) 部署上一版本代码并启动
sudo systemctl start cvplatform
```

回退前需确认代码版本与数据库结构版本匹配：若新代码已把结构升到 v2 而回退到只认 v1 的代码，
SQLite 不会自动降级，必须连同数据库一起还原（上面第 2 步已经做到）。

## 7. 本阶段未在线上执行的部分

阶段 3 只做本地实现与本地测试数据库验证，以下项目留待阶段 11 实际发布时执行并记录：

- `/var/lib/cvplatform` 的创建与授权；
- 以 `cvplatform` 用户身份的实际写入与 WAL 验证；
- `/etc/cvplatform.env` 的安装与 `EnvironmentFile` 生效确认；
- 生产库的首次初始化与线上迁移执行记录；
- 备份脚本在服务器上的首次运行结果。
