# 留白 LessLab

把收藏，变成行动。

一个使用 Python、FastAPI 和 MySQL 开发的学习收藏管理项目，
支持收藏管理、学习状态记录，以及根据时间预算生成学习计划。

## 已实现功能

- 新增收藏：记录标题、链接和预计学习时长。
- 查看收藏：展示收藏卡片，打开原文。
- 状态管理：标记已完成，或改回待学习。
- 标题搜索：支持关键词匹配，忽略英文大小写。
- 状态筛选：查看全部、待学习或已完成的收藏。
- 学习计划：输入可用时间，生成总时长不超过预算的任务列表。

## 学习计划规则

目前使用固定规则生成计划：

1. 只选择待学习、已填写有效时长的收藏。
2. 优先安排耗时短的内容；时长相同时优先选择编号小的收藏。
3. 累计预计时长不超过用户输入的时间预算。

当前尚未接入大模型，也不会自动读取文章或估算学习时长。
该规则优先安排短任务，不保证把时间预算填得最满。

## 技术栈

- Python 3.13
- FastAPI
- SQLAlchemy、PyMySQL
- MySQL 8.0
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
打开并执行项目中的 `init.sql`。

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

### 5. 启动服务

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

浏览器访问：

- 首页：http://127.0.0.1:8000/
- 接口文档：http://127.0.0.1:8000/docs
- 数据库连接检查：http://127.0.0.1:8000/health/db

停止服务：在运行服务的终端按 Ctrl+C。

## 项目文件

| 文件 | 用途 |
|---|---|
| main.py | 页面入口和后端接口 |
| database.py | 读取配置并连接 MySQL |
| index.html | 页面样式及浏览器交互 |
| init.sql | 新数据库的初始化脚本 |
| requirements.txt | Python 依赖及版本 |
| .env.example | 数据库配置模板 |
| .gitignore | 排除本地配置、虚拟环境等文件 |

## 当前范围

- 当前是本地单用户原型，尚未实现登录和用户数据隔离。
- 收藏页的搜索、筛选和统计针对最近加载的最多 100 条记录。
- 学习计划使用独立查询，不受收藏页搜索条件影响。
- 生成的计划仅展示在页面中，不保存计划历史。
- 修改收藏状态后，需要重新生成计划。
- Git 保存项目代码，不备份 MySQL 中的收藏数据。
- init.sql 用于初始化；不会自动更新已有表的结构。