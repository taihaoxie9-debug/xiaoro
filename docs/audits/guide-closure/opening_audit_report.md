# 代码评审报告

- 仓库：xiaoro-fresh
- 检测模式：通用检测
- 检测范围：frozen 7d54c58fe35f1425227e55ba07b9d896b43c5ecc / guide-closure-full-file-v1 / full_file
- 生成时间：2026-08-11 01:21
- 检查文件：147
- 变更行数：34480

## 缺陷统计

- P0：0
- P1：2
- P2：0
- 合计：2

## 缺陷详情

### 1. [P1][业务语义问题] 生产密码覆盖与客户端连接配置不一致

- 位置：`docker-compose.yml:48-51`
- 置信度：10/10

**问题描述**

生产 overlay 把 PostgreSQL 密码改为 POSTGRES_PASSWORD，并可给 Redis 设置 REDIS_PASSWORD；但 app/celery 的 DATABASE_URL 仍硬编码 postgres123，REDIS_URL 也不携带密码。只要生产设置非默认密码，Web/worker 的数据库或 Redis 连接就会确定性失败；若不设置，基础 compose 又把数据库和 Redis 端口发布到宿主机并使用弱/空凭据。

**修复建议**

让服务端与所有客户端从同一必填 secret 构造连接串，生产配置缺失时 fail closed，并避免在生产 overlay 中发布数据库/Redis 宿主端口。

---

### 2. [P1][业务语义问题] 默认部署入口仍绕过 Guide runtime

- 位置：`Dockerfile:38-38`
- 置信度：10/10

**问题描述**

所有默认 Web/worker 启动配置仍以 app.main:app 或旧 app.tasks.worker 为入口，而本 scope 内已经提供并声明 app.guide_runtime.app:app 为 Guide runtime。按当前 Dockerfile、Compose 或 start.sh 启动时会继续暴露 legacy 主链，无法兑现 Guide-only runtime 的路由、状态和错误合同。

**修复建议**

将默认 Web 启动目标统一切到 app.guide_runtime.app:app，并为仍需保留的 worker 明确拆分非公开部署；增加对所有默认 launcher 的静态门禁。

---
