# CVPlatform

计算机视觉顶会论文分析平台，采用 Vue 3 前端与 Python / FastAPI 后端。

当前阶段已完成项目初始化与前后端健康检查联通，论文采集、管理及统计功能将在后续开发。

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
│   │   ├── api/
│   │   ├── router/
│   │   └── views/
│   ├── package.json
│   └── package-lock.json
└── .venv/               # 本地虚拟环境，不提交到 Git
```

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

前端通过相对路径 `/api/health` 请求接口，Vite 将 `/api` 代理到本地后端。首页展示实际连接状态。上述代理仅用于开发；部署时需要由 Web 服务器配置相应代理。

命令直接使用虚拟环境中的解释器，无须更改 PowerShell 执行策略或激活环境。

## 验证与构建

```powershell
.\.venv\Scripts\python.exe -m pip check
npm --prefix frontend run build
```

前端构建命令包含 TypeScript 检查，输出位于 `frontend/dist`。依赖目录、虚拟环境及构建产物已由 Git 忽略规则排除。
