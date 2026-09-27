# 留白 LessLab

把收藏，变成行动。

一个使用 Python、FastAPI 和 MySQL 开发的学习收藏管理项目，
支持收藏管理、学习状态记录、按时间安排任务，以及结合学习目标生成 AI 计划。

## 已实现功能

- 新增收藏：记录标题、链接和预计学习时长。
- 查看收藏：展示收藏卡片，打开原文。
- 状态管理：标记已完成，或改回待学习。
- 归档与恢复：归档后不再参与新计划，恢复时保留原学习状态。
- 计划历史：保存 AI 计划并查看保存时的资料快照，无需再次调用模型。
- 标题搜索：支持关键词匹配，忽略英文大小写。
- 状态筛选：查看全部、待学习或已完成的收藏。
- 快速计划：按时长从短到长安排待学习内容，无需调用模型。
- AI 计划：依据目标选择收藏，显示推荐理由与本次 token 用量。
- 结果校验：检查模型返回结构、收藏编号、重复项和时间预算。

## 快速计划规则

目前使用固定规则生成计划：

1. 只选择未归档、待学习、已填写有效时长的收藏。
2. 优先安排耗时短的内容；时长相同时优先选择编号小的收藏。
3. 累计预计时长不超过用户输入的时间预算。

快速计划不调用大模型。该规则优先安排短任务，不保证把时间预算填得最满。

## AI 学习计划

配置 DeepSeek API 后，可以输入学习目标和时间预算生成 AI 建议。

1. 后端读取最近最多 20 条符合时间条件且未归档的待学习收藏。
2. 将目标、候选收藏的编号、标题和预计时长发送给 DeepSeek。
3. 模型最多选择 8 项内容，并提供基于标题的推荐理由。
4. Python 校验返回结构、编号、重复项与总时长；不合格的计划会被拒绝。
5. 网页展示通过校验的计划和模型返回的 token 用量。

项目不自动读取链接正文，学习时长由用户填写。
没有候选收藏时不调用模型；每次生成请求最多调用模型一次，不自动重试。
模型超时或输出不合格时会显示错误，用户仍可主动使用独立的快速计划入口。

模型调用按配置的 API Key 所属账户计费。生成失败不一定代表没有产生用量，
实际费用以模型平台记录为准。当前尚未实现账户限额或全站预算控制。

## 技术栈

- Python 3.13
- FastAPI
- SQLAlchemy、PyMySQL
- MySQL 8.0
- HTTPX、DeepSeek API
- Python unittest（离线自动化测试）
- HTML、CSS、JavaScript
- Git

## 本地启动（Windows PowerShell）

### 1. 准备环境

安装 Python 3.13 和 MySQL 8.0，确保 MySQL 服务正在运行。

下载项目后，在 VS Code 中打开项目文件夹。
下面的终端命令均在项目根目录执行。

### 2. 安装 Python 依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. 初始化数据库

在 Navicat 中使用拥有建库、建表权限的管理员连接，
首次安装按顺序执行：

1. `init.sql`
2. `migrations/001_create_study_plans.sql`
3. `migrations/002_add_resource_archive.sql`

已有数据库只执行尚未应用的迁移。002 添加 `resources.archived_at` 字段，
只执行一次；可先运行 `SHOW COLUMNS FROM lesslab.resources LIKE 'archived_at';` 检查。
升级期间先停止服务，完成迁移与代码更新后再启动。

随后在管理员查询窗口中创建应用专用账号。
执行前，将下面的密码占位文字换成自己设置的密码。
不要把实际密码写回本说明文件或提交到 Git。

```sql
CREATE USER 'lesslab_app'@'127.0.0.1'
IDENTIFIED BY 'replace_with_your_password';

GRANT SELECT, INSERT, UPDATE, DELETE
ON lesslab.*
TO 'lesslab_app'@'127.0.0.1';
```

以上创建账号的语句用于首次安装。
如果账号已经存在，请使用该账号已有的配置，不要重复创建。

### 4. 配置环境变量

首次安装且没有 `.env` 时，复制模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填写实际数据库地址、端口、账号和密码。

已有 `.env` 时不要覆盖。数据库密码只保存在本地配置中。

### 5. 配置 AI（可选）

如果需要 AI 计划，在本地 `.env` 中填写：

```dotenv
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

真实密钥只放在 `.env`，不要放入网页或提交到 Git。
不配置密钥时仍可使用收藏管理与快速计划，AI 接口会提示未配置。

可选连接测试（会发送一次真实请求，可能产生费用）：

```powershell
.\.venv\Scripts\python.exe check_deepseek.py
```

模型名称和计费方式以 [DeepSeek 官方文档](https://api-docs.deepseek.com/zh-cn/)为准。

### 6. 启动服务

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

浏览器访问：

- 首页：http://127.0.0.1:8000/
- 接口文档：http://127.0.0.1:8000/docs
- 数据库连接检查：http://127.0.0.1:8000/health/db

停止服务：在运行服务的终端按 Ctrl+C。

## 自动化测试

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用模拟配置、模型响应以及内存 SQLite 数据库检查接口行为，不读取真实 `.env`，
不访问 MySQL，不调用 DeepSeek，也不消耗模型额度。

覆盖有效计划、预算边界、无效或重复编号、异常返回、超时、缺少密钥、
无候选收藏和请求参数校验等情况。
这些测试不替代真实数据库集成测试、页面测试或推荐质量评估。

## 项目文件

| 文件 | 用途 |
|---|---|
| main.py | 页面入口和后端接口 |
| database.py | 读取配置并连接 MySQL |
| archive_routes.py | 资料归档与恢复接口 |
| plan_routes.py | 保存与读取计划历史 |
| static/collections.js | 收藏与归档网页交互 |
| migrations/ | 按顺序执行的数据库迁移 |
| tests/test_archive.py | 归档、恢复和计划排除的离线测试 |
| ai_routes.py | AI 计划接口与结果校验 |
| check_deepseek.py | 可选的真实模型连接测试 |
| index.html | 页面样式及浏览器交互 |
| static/ai_plan.js | AI 计划的网页交互 |
| tests/test_ai_plan.py | AI 接口的离线自动化测试 |
| init.sql | 新数据库的初始化脚本 |
| requirements.txt | Python 依赖及版本 |
| .env.example | 数据库配置模板 |
| .gitignore | 排除本地配置、虚拟环境等文件 |

## 当前范围

- 当前是本地单用户原型，尚未实现登录和用户数据隔离。
- 收件箱和归档列表分别加载各自最近最多 100 条记录；收藏搜索和筛选在这 100 条内进行。
- 学习计划使用独立查询，不受收藏页搜索条件影响。
- AI 计划需要点击保存才会进入历史；快速计划目前只在页面展示。
- 归档只影响之后生成的计划；保存过的历史快照不会改写。
- 归档和恢复使用数据库操作，不消耗模型额度。
- 修改收藏状态后，需要重新生成计划。
- Git 保存项目代码，不备份 MySQL 中的收藏数据。
- init.sql 用于初始化；不会自动更新已有表的结构。
## 许可证

项目代码采用 MIT 许可证，详见 [LICENSE](LICENSE)。
