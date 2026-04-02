# GitHub 自动部署配置指南

## 1. 初始化远端仓库

在本地项目目录执行：

```bash
git init
git add .
git commit -m "init remote literature v1"
git branch -M main
git remote add origin git@github.com:<your-account>/<your-repo>.git
git push -u origin main
```

## 2. GitHub Secrets

在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 添加：

- `VPS_HOST`：VPS 公网 IP 或域名
- `VPS_PORT`：SSH 端口（默认 `22`）
- `VPS_USER`：SSH 用户（如 `root`）
- `VPS_SSH_KEY`：私钥全文（用于 Actions SSH 登录）
- `VPS_PATH`：项目在 VPS 的目标路径（如 `/root/文献管理html`）
- `PROD_ENV_FILE`：生产环境 `.env` 全文

## 3. 生产环境 `.env` 建议最小项

```env
DATABASE_URL=postgresql+psycopg://literature:literature@postgres:5432/literature
REDIS_URL=redis://redis:6379/0
SITE_HOST=hqysuda.xyz
LLM_ENABLED=false
API_ADMIN_TOKEN=<long-random-token>
STORAGE_ROOT=/app/remote-data
LIBRARY_FILES_DIR=/app/literature-library/files
UPLOAD_TMP_DIR=/app/remote-data/uploads
```

## 4. 首次部署

首次推送 `main` 后，GitHub Actions 会自动：

1. 通过 SSH 连接 VPS
2. rsync 同步代码到 `VPS_PATH`
3. 写入 `.env`
4. 执行 `docker compose up -d --build`
5. 健康检查 `http://127.0.0.1:8080/api/health`

## 5. 日常维护流程

```bash
git add .
git commit -m "feat: update ui and retrieval"
git push origin main
```

推送后等待 Actions 成功即可，无需手工登录 VPS 改代码。

## 6. 回滚

方式一（推荐）：

1. 给稳定版本打 tag（例如 `v1.0.3`）
2. 在 Actions 手动触发 `deploy`
3. 填写 `rollback_ref=v1.0.3`

方式二：

- 在本地回退到目标 commit 并 push 到 `main`
