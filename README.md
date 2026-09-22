# CVPlatform

计算机视觉顶会论文分析平台，采用 Vue 3 前端与 Python / FastAPI 后端。

当前进度：论文管理与论文详情已接入真实后端接口（SQLite 持久化）；单篇采集已接入真实外部来源
（CVF Open Access、ECVA 与 OpenAlex 兜底检索），并按标题产出系统关键词；热门方向总览、
热度走势对比仍使用集中管理的演示数据并已标注，将在阶段 8、9 接入统计接口。

## 开发环境

- Python 3.12（项目根目录 `.venv`，与系统 Python 隔离）
- Node.js 24.15.0、npm 11.12.1
- 前端：Vue 3、Vite、TypeScript、Vue Router
- 后端：FastAPI、Uvicorn、SQLModel、python-multipart

## 目录

```text
CVPlatform/
├── backend/
│   ├── app/
│   │   ├── config.py     # 配置与数据库路径解析（开发/测试/生产）
│   │   ├── db/           # 引擎、会话与版本化迁移
│   │   ├── models/       # SQLModel 实体
│   │   ├── schemas/      # 请求与响应契约
│   │   ├── services/     # 论文服务层、关键词抽取、采集编排与外部来源
│   │   ├── routers/      # /api/papers 与 /api/collect 接口
│   │   └── main.py       # 应用入口、统一错误响应、健康检查
│   ├── tests/            # 独立临时数据库上的测试
│   ├── requirements.txt     # 运行时依赖
│   └── requirements-dev.txt # 开发与测试依赖（生产不装）
├── deploy/               # 生产配置模板、备份脚本、升级回退说明
├── frontend/
│   ├── src/
│   │   ├── api/          # HTTP 请求（health、paperApi）
│   │   ├── components/   # 可复用组件
│   │   ├── composables/  # 组合式函数（轻提示）
│   │   ├── demo/         # 尚未接入接口的页面所用演示数据
│   │   ├── layouts/      # 公共布局
│   │   ├── router/       # 六个页面路由
│   │   ├── styles/       # 设计令牌与公共 UI 样式
│   │   ├── types/        # 领域类型（字段与后端契约一致）
│   │   └── views/        # 页面组件
│   ├── package.json
│   └── package-lock.json
└── .venv/               # 本地虚拟环境，不提交到 Git
```

## 页面入口

| 路径 | 页面 | 数据来源 |
|---|---|---|
| `/` | 热门方向总览 | 演示数据（阶段 8 接入统计接口） |
| `/trends` | 热度走势对比 | 演示数据（阶段 9 接入趋势接口） |
| `/papers` | 论文管理 | **后端接口 `/api/papers`** |
| `/papers/:id` | 论文详情 | **后端接口 `/api/papers/{id}`** |
| `/collect` | 采集与导入 | 后端接口 `/api/collect/*` 已就绪；界面联调与批量导入在阶段 6 |
| `/about` | 关于平台 | 静态说明 |

数据边界：已接入接口的页面直接显示数据库内容，不混用演示数据；未接入的页面在页头标注
「演示数据 / 尚未接入后端接口」，且不显示虚假的处理进度。

## 安装依赖

首次取得仓库后，在项目根目录执行以下 PowerShell 命令。当前电脑已完成安装，可直接启动。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm --prefix frontend ci
```

## 启动开发服务

在项目根目录打开两个终端。

终端一，启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

终端二，启动前端：

```powershell
npm --prefix frontend run dev
```

- 前端页面：<http://127.0.0.1:5173>
- 后端健康检查：<http://127.0.0.1:8000/api/health>
- 后端接口文档：<http://127.0.0.1:8000/docs>

前端通过相对路径 `/api/health` 请求接口，Vite 将 `/api` 代理到本地后端。后端连接状态显示在每个页面页脚（含“重新检查”），后端未启动时显示“未连接”。上述代理仅用于开发；部署时需要由 Web 服务器配置相应代理。

命令直接使用虚拟环境中的解释器，无须更改 PowerShell 执行策略或激活环境。

## 验证与构建

```powershell
.\.venv\Scripts\python.exe -m pip check
npm --prefix frontend run build
```

前端构建命令包含 TypeScript 检查，输出位于 `frontend/dist`。依赖目录、虚拟环境及构建产物已由 Git 忽略规则排除。

页面结构与交互可在浏览器中核对：六个路由均可直接访问与刷新（Vue Router history 模式，部署时需由 Web 服务器配置回退到 `index.html`）。
