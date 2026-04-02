# 远端交互式 AI 文献库 V1

## 1. 架构

- `caddy`：对外静态页面与 API 反向代理
- `api`：FastAPI 服务（检索、文献查询、上传任务、编辑）
- `worker`：异步任务消费者（解析上传文件、解析 URL）
- `postgres`：元数据与任务状态
- `redis`：任务队列

核心目录：

- `remote_app/`：后端 API + 检索 + 任务处理
- `remote-ui/`：前端页面（`index.html` 公开检索、`admin.html` 管理台）
- `scripts/migrate_papers_to_db.py`：一次性迁移 `papers.json` 到数据库

## 2. 启动

1. 复制环境变量：

```bash
cp .env.example .env
```

2. 启动容器：

```bash
docker compose up -d --build
```

3. 初始化迁移：

```bash
docker compose exec api python scripts/migrate_papers_to_db.py
```

## 3. 访问路径

- 公网检索页：`https://<your-domain>/`
- 公网只读 API：
  - `GET /api/health`
  - `GET /api/categories`
  - `GET /api/papers?page=1&page_size=24&category=&sort=updated_desc&q=`
  - `GET /api/search?q=...`
  - `GET /api/papers/{id}`
  - `GET /files/<filename>`（原文静态访问）

管理能力为 Token 保护（必须带 `X-Admin-Token`）：

- 管理台：`/admin.html`
- 管理 API：
  - `POST /api/ingest/upload`
  - `POST /api/ingest/url`
  - `GET /api/tasks`
  - `GET /api/tasks/{id}`
  - `GET /api/admin/papers?status=pending_review`
  - `POST /api/admin/papers/{id}/publish`
  - `POST /api/admin/papers/{id}/reject`
  - `POST /api/papers/{id}/update`

`API_ADMIN_TOKEN` 未配置时，管理接口会返回 `500 admin_token_not_configured`。

## 4. AI 搜索链路

`normalize query -> rewrite hook -> candidate retrieval -> rerank hook -> explain`

- 本地候选召回保留：词法匹配 + 哈希向量相似度混合打分
- LLM 仅用于可选的 query rewrite / rerank / explain
- 未配置模型时自动退化到本地检索模式

## 5. 上传与解析

- 文件上传支持：`PDF / DOCX / TXT / MD / HTML / ZIP`
- URL 解析：抓取网页正文并入库
- 异步任务状态：`queued / running / success / failed`
- 混合发布策略：
  - `analysis_confidence >= 0.75`：自动发布（`published`）
  - `< 0.75`：进入待审（`pending_review`）

## 6. SSH 隧道示例（管理台）

```bash
ssh -L 18080:127.0.0.1:8080 root@<your-vps-ip>
```

本地打开：

`http://127.0.0.1:18080/admin.html`

## 7. 自动部署（GitHub Actions）

工作流文件：

- `.github/workflows/deploy.yml`

触发方式：

- `push main` 自动部署
- 手动触发并填写 `rollback_ref` 可以回滚到指定 tag/commit

需要配置 GitHub Secrets：

- `VPS_HOST`
- `VPS_PORT`
- `VPS_USER`
- `VPS_SSH_KEY`
- `VPS_PATH`
- `PROD_ENV_FILE`（完整 `.env` 内容）

完整步骤见：`docs/GITHUB_AUTODEPLOY_SETUP.md`
