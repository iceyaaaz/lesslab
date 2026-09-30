# 免费演示部署：Render + Aiven MySQL

网页运行在 Render，数据库运行在 Aiven，电脑关闭后仍可访问。固定网址由 Render 提供，
不需要购买域名。免费服务存在休眠、资源配额和平台政策限制，不承诺永久在线。

## 当前状态

部署适配代码和离线测试已准备。本说明不代表云端服务已经上线；需要完成下面的控制台配置和验收。
Render 使用 Python 3.13（由仓库根目录 .python-version 指定），不需要 Docker。

## 1. 云数据库准备

在 Aiven 创建 MySQL Free 服务，用 Navicat 配置 CA 证书并连接。
云端 lesslab 数据库须包含项目的 10 张表；可以从当前本地数据库导出“结构和数据”，
导入云端空库。先对比本地、云端 users、resources、study_plans、user_goals、
study_plan_progress 的记录数量，确认没有漏数据。

导入完整备份后，不再重复执行 init.sql、001—005 或 setup_owner.py。
原网站账号密码可以用于云端登录；它们与 Aiven 数据库连接账号是两回事。
数据库备份包含账号和业务数据，不提交到 GitHub。

下载 Aiven 服务的 CA Certificate 文件，保留完整 PEM 内容。

## 2. 创建 Render 网站

在 Render 控制台选择 New → Web Service，通过 GitHub 选择 iceyaaaz/lesslab。
如果 GitHub 要求授权，范围只选择这个仓库。不要选择 Static Site 或新建 Render 数据库。

| 设置 | 内容 |
|---|---|
| Name | lesslab（重名时平台会调整网址，以最终显示为准） |
| Branch | main |
| Language / Runtime | Python 3 |
| Root Directory | 留空 |
| Build Command | pip install -r requirements.txt |
| Start Command | python -m uvicorn main:app --host 0.0.0.0 --port $PORT |
| Instance Type | Free / $0 |
| Health Check Path（若可设置） | /health |

不要在启动命令中添加 --reload。/health 只验证网页进程，数据库仍需通过登录和实际保存验证。
在创建前填写下面的环境变量与证书。如果界面尚未提供 Secret Files，可先创建服务，
再到 Environment 添加证书并重新部署；缺少证书时应用会拒绝启动，不会明文连接云数据库。

## 3. Environment Variables

手工填写以下变量。不要把本地 .env 整份上传，否则 localhost 地址和本地配置会覆盖云端设置。

| Key | Value |
|---|---|
| DB_HOST | Aiven 的 Host，不带协议，不填写 localhost |
| DB_PORT | Aiven 显示的 Port，不假设为 3306 |
| DB_USER | 云数据库用户；与 Navicat 云连接使用的用户对应 |
| DB_PASSWORD | 这个云数据库用户的密码，只填在平台配置里 |
| DB_NAME | lesslab |
| DB_SSL_CA | /etc/secrets/aiven-ca.pem |
| AUTH_COOKIE_SECURE | true |
| AUTH_ALLOW_REGISTRATION | false（先验证已有账号；需要开放注册时再改为 true） |
| DEEPSEEK_API_KEY | 留空；如果控制台不接受空值，暂时不添加该变量 |

APP_ORIGIN 暂时不要添加：程序会使用 Render 自动提供的 RENDER_EXTERNAL_URL，
与分配到的 HTTPS 网址保持一致。以后绑定自定义域名，才将 APP_ORIGIN 显式设为该地址，
不带末尾斜线。若它错误地设为 http://127.0.0.1:8000，请删除这个云端变量并重新部署。

DB_USER 是数据库连接用户，users 表内的用户名是网站登录用户，不要混淆。
部署成功后，建议给网站使用仅具有 lesslab 库 SELECT、INSERT、UPDATE、DELETE 权限的
专用数据库账号；建表和迁移由维护者的数据库连接执行。

## 4. Secret Files

在服务的 Environment → Secret Files → Add Secret File 中：

- Filename：aiven-ca.pem
- Contents：用文本编辑器打开 Aiven 下载的 CA 文件，粘贴完整内容。
  包括 BEGIN CERTIFICATE、END CERTIFICATE 和中间所有行；不要粘贴本机文件路径。

这个文件在 Render 上的位置是 /etc/secrets/aiven-ca.pem，须与 DB_SSL_CA 一致。
不要粘贴数据库密码或 API Key 到证书文件里。
保存后选择部署/重新部署。程序验证 CA 及服务器主机名，证书错误会失败，不会跳过校验。

## 5. 验收

等服务显示 Live 后，打开 Render 实际显示的 https://...onrender.com 网址。

1. 用迁移前的网站账号登录，核对旧收藏、目标、计划和进度。
2. 新建一条测试收藏，刷新后确认保留；需要时再归档。
3. 退出后直接访问首页，应回到登录页。
4. 关闭本机网页服务，手机切换到移动数据，再打开云端网址。

这些步骤不调用模型。首次唤醒可能较慢，先等网页服务完成启动。
本地数据库和云数据库从迁移后是两份独立数据，不自动互相同步；再次导入旧备份会覆盖云端新数据。

## AI 配置（可选，有费用）

不配置 DEEPSEEK_API_KEY 时，登录、收藏、目标、历史和快速计划可用，AI 入口会提示未配置。
若以后决定使用付费 AI，在 Render 添加 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、DEEPSEEK_MODEL 并部署。
平台环境变量优先于 .env；环境变量中的空密钥会停用 AI，不回退到文件里的密钥。
模型名称以模型平台可用列表为准。AI 费用由密钥所属账号承担，与 Render/Aiven 免费额度无关。
本项目尚无 AI 用量限制或保存防重复机制，本次不增加这些功能。

## 费用与数据保存

- 选择 Render Free 和 Aiven MySQL Free，使用平台子域名，不开通付费功能。
- Render 免费网页闲置 15 分钟会休眠，下次请求唤醒通常约一分钟；超配额可能暂停。
- Aiven 免费库有 1 GB 存储，无固定试用期限，但不活跃时可能暂停，需到控制台恢复。
- Render 的临时磁盘不能用于持久化数据库；业务数据保存在 Aiven，并自行定期导出备份。
- 若平台显示收费或要求选择付费资源，停止当前购买步骤，不把付费试用当作免费方案。

## 排错

- ModuleNotFoundError / 安装失败：检查使用 Python 3.13、仓库和 Build Command 是否正确。
- 缺少 DB_SSL_CA / 证书文件：核对 Secret File 名称与完整 PEM 内容，保存后重新部署。
- Invalid host header：检查 APP_ORIGIN 是否误用了本机地址或另一临时网址。
- 数据库不可用：检查 Aiven 服务状态、连接用户、端口、库名及证书，不要关闭证书校验。
- 没有 users 表：导入位置可能不正确，确认 Navicat 云连接下的 lesslab 中有全部 10 张表。

参考：
- https://render.com/docs/deploy-fastapi
- https://render.com/docs/python-version
- https://render.com/docs/configure-environment-variables
- https://render.com/docs/free
- https://aiven.io/docs/products/mysql/concepts/mysql-free-tier
- https://aiven.io/docs/platform/concepts/tls-ssl-certificates
