# CVPlatform

计算机视觉顶会论文分析平台，采用 Vue 3 前端与 Python / FastAPI 后端。

当前阶段已完成前端六类页面的结构与交互（热门方向总览、热度走势对比、论文管理、论文详情、采集与导入、关于平台），
页面数据全部来自集中管理的演示数据并已标注，**尚未接入后端业务接口**；论文采集、持久化与统计接口将在后续开发。

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
│   │   └── main.py       # FastAPI 入口与 /api/health
│   └── requirements.txt # 当前后端环境的依赖版本
├── frontend/
│   ├── src/
│   │   ├── api/          # HTTP 请求（当前仅 health）
│   │   ├── components/   # 可复用组件（导航、筛选、表格、弹窗、图表容器等）
│   │   ├── composables/  # 组合式函数（轻提示）
│   │   ├── demo/         # 集中管理的演示数据，接入接口后逐项删除
│   │   ├── layouts/      # 公共布局（页头 + 内容 + 页脚 + 提示）
│   │   ├── router/       # 六个页面路由
│   │   ├── styles/       # 设计令牌与公共 UI 样式
│   │   ├── types/        # 领域类型（与后端契约对应）
│   │   └── views/        # 页面组件
│   ├── package.json
│   └── package-lock.json
└── .venv/               # 本地虚拟环境，不提交到 Git
```

## 页面入口

| 路径 | 页面 | 说明 |
|---|---|---|
| `/` | 热门方向总览 | 会议/年份筛选、KPI、Top 10 榜单、关键词图谱容器、相关论文抽屉 |
| `/trends` | 热度走势对比 | 主题与会议筛选、播放/暂停/重播、年份定位、趋势与年度 Top 10 两个视图 |
| `/papers` | 论文管理 | 搜索（精确/模糊）、多会议与年份区间筛选、排序、分页、新增/编辑/删除 |
| `/papers/:id` | 论文详情 | 摘要、两类关键词、数据来源、方向热度、相关论文、编辑 |
| `/collect` | 采集与导入 | 单篇采集表单与结果区状态、批量导入模板与任务区 |
| `/about` | 关于平台 | 数据来源、覆盖范围、关键词方法、热度口径与图谱读法 |

演示数据边界：`src/demo/` 集中存放演示数据，页头统一标注「演示数据 / 尚未接入后端接口」；
尚未接入后端的写入操作在提示中明确说明「仅在本页内存中生效」，不伪造接口成功与处理进度。

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
