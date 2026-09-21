# CVPlatform 代码规范

> **规范来源**
>
> - Python：[Python 官方 PEP 8](https://peps.python.org/pep-0008/)。
> - TypeScript：[Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html)。
> - Vue：[Vue 官方风格指南](https://vuejs.org/style-guide/)与 [Vue 3 `<script setup>` 文档](https://vuejs.org/api/sfc-script-setup.html)。
>

## 1. 适用范围与执行原则

- 后端：Python 3.12、FastAPI、SQLModel、SQLite。
- 前端：Vue 3、TypeScript、Vite、Vue Router。
- 优先保证逻辑正确、命名清晰和模块内一致性；避免为格式调整无关业务代码。
- 新增和修改的代码遵守本规范，未修改的历史代码不要求一次性全部重排。
- 自动生成的依赖锁文件与第三方代码不手工重排；依赖锁文件由包管理器维护。
- 代码是否遵守规范与功能是否通过测试分别检查，不能相互替代。

## 2. 通用格式（项目约定）

| 项目 | 约定 |
|---|---|
| 编码 | UTF-8，不带 BOM |
| 换行 | 文本文件使用 LF；`.bat`、`.cmd` 使用 CRLF，以 `.gitattributes` 为准 |
| 缩进 | Python 使用 4 个空格；TypeScript、Vue、CSS、JSON 使用 2 个空格 |
| 行尾 | 不留无意义的尾随空格；文件末尾保留一个换行 |
| 行宽 | Python 代码目标 88 字符；前端代码目标 100 字符，长 URL 和不宜拆分的内容允许例外 |
| 注释语言 | 中文或英文均可，说明准确，同一模块尽量一致 |
| 标识符 | 使用表达业务含义的英文，不用拼音、无意义编号或随意缩写 |

Python 的 88 字符行宽是本项目约定，不是 PEP 8 默认的 79 字符；注释和文档字符串中的自然段尽量按 PEP 8 的 72 字符建议换行。代码换行优先使用括号包围的多行表达式。

## 3. Python 规范

### 3.1 基于 PEP 8 的规则

- 模块、函数和变量使用 `snake_case`，如 `paper_service.py`、`get_paper`。
- 类名使用 `PascalCase`，如 `PaperCreate`；常量使用 `UPPER_SNAKE_CASE`。
- 标准库、第三方库、本项目模块的导入分组排列，组间空一行；不使用通配符导入。
- 顶层类和函数之间空两行，类中的方法之间空一行。
- 与 `None` 比较使用 `is None`、`is not None`。
- 捕获具体异常，避免裸 `except:`；使用上下文管理器管理可关闭资源。

### 3.2 后端项目约定

- 普通字符串优先双引号；文档字符串使用三重双引号。
- 对接口、服务层等模块间调用的函数声明参数及返回类型；使用 Python 3.12 支持的 `list[str]`、`str | None` 等写法。
- 用请求模型校验输入，用响应模型约束输出；不要直接返回可能含内部字段的数据库对象。
- 路由负责参数与 HTTP 响应，复用的采集、统计和持久化逻辑按实际需要拆成函数或模块，不强制为空目录建立复杂分层。
- 使用数据库参数绑定或 ORM 表达式，不把用户输入直接拼入 SQL。
- 文件路径使用 `pathlib.Path`；项目配置不写死个人电脑的绝对路径。
- 外部网络请求设置超时；异步函数中避免直接执行会长时间阻塞事件循环的同步请求。
- 业务预期错误转换为清楚的接口错误；未知错误记录必要日志，不返回密码、内部路径或完整堆栈给用户。

命名与类型示例（仅说明规范，不代表当前已实现的业务接口）：

```python
from pydantic import BaseModel


class PaperCreate(BaseModel):
    title: str
    conference: str
    year: int


def normalize_title(title: str) -> str:
    """Trim and collapse whitespace without changing title capitalization."""
    return " ".join(title.split())
```

## 4. TypeScript 规范

### 4.1 参考 Google 指南的规则

- 变量、参数和函数使用 `camelCase`，类型与接口使用 `PascalCase`。
- 优先使用 `const`；确需重新赋值时使用 `let`，不使用 `var`。
- 普通字符串使用单引号；插值字符串使用模板字符串。
- 不用 `any` 逃避类型检查；未知输入使用 `unknown` 并缩小类型范围。
- 仅为消除报错而添加的类型断言或非空断言不可接受，应先处理实际空值或类型分支。

### 4.2 与上游的差异及前端项目约定

- **延续现有项目不写语句末尾分号的风格**，这是对 Google 指南的项目级调整。避免以 `(`、`[` 等可能触发自动分号插入歧义的表达式开头，必要时使用防御性分号或改写语句。
- TypeScript 工具文件使用与现有代码一致的名称，如 `health.ts`；新增多词文件使用 `camelCase`，如 `paperApi.ts`。
- 导出的 API 函数明确返回类型；组件中的局部变量优先依赖可靠的类型推断。
- HTTP 请求集中到 `src/api/` 的相应模块，页面不重复拼接同一套请求逻辑。
- `as Paper` 只影响静态类型，不会验证网络数据；不要把断言当作运行时校验。
- 请求处理区分加载、成功、空数据和失败；使用 `finally` 恢复加载状态，避免错误分支让按钮永久禁用。
- 需要顺序的数据请求按依赖执行；快速切换筛选时避免旧响应覆盖新结果。

示例：

```ts
export interface PaperSummary {
  id: number
  title: string
  year: number
}

export function formatPaperLabel(paper: PaperSummary): string {
  return `${paper.title} (${paper.year})`
}
```

## 5. Vue 与样式规范

采用 Vue 3 Composition API 和 `<script setup lang="ts">`。组件命名、列表稳定键和清晰的数据流参考 Vue 官方指南；具体目录、区块顺序和样式组织采用以下项目约定。

- 单文件组件使用 `PascalCase`，业务组件使用多词名称，如 `PaperTable.vue`；根组件 `App.vue` 除外。
- 页面组件放在 `src/views/`，复用组件放在 `src/components/`；有复用需求时再提取组合式函数。
- 单文件组件顺序统一为 `script setup`、`template`、`style`，延续当前代码布局。
- Props 和事件定义明确类型；不直接修改父组件传入的数据，通过事件传递修改意图。
- `v-for` 使用稳定唯一标识作为 `key`，论文列表使用论文 ID，避免用会随排序变化的数组下标。
- 模板中的复杂计算移到 `computed` 或函数，不在模板中堆积难以阅读的表达式。
- 表单控件提供标签；图标按钮有可访问名称；使用语义明确的按钮和链接。
- 局部样式优先 `scoped`，全局主题样式集中维护；CSS 类名使用 `kebab-case`。
- CSS 声明保留分号，HTML 属性使用双引号；这与 TypeScript 的分号约定分别执行。
- 以已确认的墨刀原型为界面依据；重复的颜色和间距逐步复用，不自行切换科技风。
- 图表、事件监听和播放计时器在组件卸载时释放，避免重复创建后残留。

## 6. 接口与领域数据（项目约定）

- URL 使用小写资源名，沿用 `/api` 前缀；多词路径使用连字符。
- JSON 字段命名沿用已确认的数据契约。新契约默认使用 `snake_case`，前端类型准确反映实际字段；不要在同一接口中随意混用命名方式。
- 使用有明确含义的状态值与单位；缺失数据使用契约定义的空值，不把它强行写成 `0`。
- 用户输入在服务端校验，前端校验仅用于改善体验。
- 区分论文原始信息、系统提取信息和演示数据；不得用随机数据填补真实统计缺失。
- 关键词规范化、论文去重和热度计算集中维护，页面与接口复用相同口径。
- 注释重点解释计算公式、数据来源限制、去重规则和设计原因，不重复描述显而易见的赋值语句。

## 7. AI 代码与人工复核（课程项目约定）

- AI 生成代码同样遵守本规范，提交者需要理解其输入、输出、异常分支及主要设计。
- 不引入自己无法解释的依赖或抽象，不复制原型工具生成的成品代码。
- 对真实修改记录采纳或拒绝 AI 建议的理由；不虚构验证结果和人工贡献。
- 修复实际 Bug 时，优先补能复现问题的验证用例，再确认修复有效。
- 每阶段完成后按约定等待人工复核；代码规范检查不能替代原型和功能验收。

## 8. 检查方式与提交要求

当前仓库没有配置专门的 ESLint、Prettier 或 Ruff 检查命令。本文是编码与人工复核依据，不代表这些规则已经自动执行。后续若引入格式化工具，其配置须与本文同步。

目前可在项目根目录执行：

```powershell
# 包含前端类型检查与生产构建
npm --prefix frontend run build

# 检查后端依赖一致性；不代替代码风格或业务测试
.\.venv\Scripts\python.exe -m pip check

# 检查未暂存/已暂存补丁中的空白问题
git diff --check
git diff --cached --check
```

复核时检查命名、类型、异常处理、资源释放和真实业务行为。涉及采集、去重、统计或数据修改时，执行相应业务测试；格式与文档修改无需增加无关测试。

提交前检查实际暂存内容，遵守 `.gitignore`，不提交虚拟环境、依赖目录、构建产物、真实环境密钥和本地数据库。README、`codestyle.md`、依赖清单、锁文件以及脱敏配置示例应正常入库。

提交说明使用“动作 + 具体内容”，例如 `实现论文标题精确查询`，避免只有 `update` 或 `fix`。提交次数与协作记录按真实工作形成，不通过无意义提交凑数。
