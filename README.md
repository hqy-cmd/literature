# agent文献库

一个面向科技/工程文献整理的本地 HTML 文献库工具。

## 当前能力

- 导入 PDF / DOCX / TXT / Markdown / HTML / ZIP
- 自动抽取标题、摘要、年份、作者（尽力而为）
- 按二级菜单结构整理文献集合
- 生成移动端友好的本地浏览页面
- 可同步发布到远程服务器

## 目录结构

```text
文献管理html/
  literature-library/        # 实际对外展示的文献库
    index.html
    papers.json
    files/
  incoming/                  # 待导入文献
  processed/                 # 已处理原文归档
  scripts/
    update_library.py        # 主更新脚本
    start_library_server.py  # 本地微服务启动脚本
  config/
    deploy_config.json       # 自动同步配置
  docs/
    USAGE.md
    DEPLOY.md
  archive/
    legacy-papers-v1.json    # 旧版初始化数据备份
  启动文献库.command
```

## 使用方法

### 本地使用

双击：

`启动文献库.command`

或手动执行：

```bash
cd ~/Desktop/文献管理html
python3 scripts/update_library.py
python3 scripts/start_library_server.py
```

本地访问：

`http://127.0.0.1:8765/index.html`

### 导入新文献

把文献放进：

`~/Desktop/文献管理html/incoming/`

然后运行：

```bash
python3 ~/Desktop/文献管理html/scripts/update_library.py
```

## 自动同步

同步配置在：

`config/deploy_config.json`

当前逻辑：更新本地文献库后，会尝试自动 rsync 到远程服务器。

若要真正自动发布成功，需要先配置 SSH 免密登录。

---

## 远端交互式 V1（新增）

项目已新增一套远端交互版本，支持：

- 统一后端智能搜索（支持 query rewrite / rerank 的 LLM hook）
- 远端上传文献并异步解析
- URL 网页正文解析入库
- 任务状态追踪
- 内网管理台编辑文献元数据

主要目录：

- `remote_app/`：FastAPI + Worker
- `remote-ui/`：前端（公开检索页 + 管理台）
- `docker-compose.yml`：`caddy + api + worker + postgres + redis`
- `scripts/migrate_papers_to_db.py`：将 `literature-library/papers.json` 迁移到数据库

详见：

- `docs/REMOTE_V1.md`
- `docs/GITHUB_AUTODEPLOY_SETUP.md`

远端 V1 当前默认体验：

- 公开首页为“分类目录 + 分页浏览”（搜索为增强入口）
- 管理台改为公网可访问，但写接口必须携带 `X-Admin-Token`
- 支持 `GitHub Actions` 自动部署到 VPS（`push main`）
