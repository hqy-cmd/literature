# 文献管理系统恢复与接班指南

> 目的：如果小龙虾突然掉线、会话重置、或需要换新实例，这份文档能让下一任快速恢复系统。

## 一、系统是什么

这是一个**本地维护 + 自动生成 HTML + 可同步发布到个人网站**的文献管理系统。

核心思路：
1. 把新文献放入待处理目录；
2. 用脚本抽取标题/摘要/年份/作者；
3. 生成本地静态文献站；
4. 同步到远端网站目录；
5. 本地与远端都能浏览。

## 二、当前目录结构

```text
文献管理html/
  literature-library/        # 最终对外展示的静态站点
    index.html
    papers.json
    files/
  inbox/                     # 监听模式使用的投递目录
  incoming/                  # 手动导入时的待处理目录
  processed/                 # 已处理原文归档
  scripts/
    update_library.py        # 主更新脚本（最关键）
    start_library_server.py  # 本地预览服务
    watch_inbox.py           # 监听 inbox，逐个处理新文件
  config/
    deploy_config.json       # 远端发布配置
  docs/
    USAGE.md
    DEPLOY.md
    RECOVERY_GUIDE.md
  启动文献库.command
  启动监听.command
```

## 三、最关键的事实

### 1. 当前部署记录是存在的，不需要从零摸索
已确认本地存在：
- `docs/DEPLOY.md`
- `config/deploy_config.json`
- 自动同步逻辑写在 `scripts/update_library.py`

### 2. 当前远端发布配置
配置文件：`config/deploy_config.json`

当前内容等价于：
```json
{
  "enabled": true,
  "host": "218.244.147.33",
  "user": "root",
  "remote_path": "/var/www/literature-library/"
}
```

### 3. 2026-03-28 已重新验证部署链路
执行：
```bash
python3 scripts/update_library.py
```
返回结果显示：
- `auto_sync.enabled = true`
- `auto_sync.ok = true`
- 目标：`root@218.244.147.33:/var/www/literature-library/`

结论：**文献库当前仍然可以成功推送到个人网站。**

## 四、标准工作流程

### 方案 A：手动导入（最稳）
适合：临时维护、排障、换新 agent 后先恢复功能。

#### 步骤 1：把新文献放进 incoming/
支持格式：
- PDF
- DOCX
- TXT
- Markdown
- HTML
- ZIP

目录：
```bash
~/Desktop/文献管理html/incoming/
```

#### 步骤 2：执行主更新脚本
```bash
cd ~/Desktop/文献管理html
python3 scripts/update_library.py
```

这个脚本会：
1. 读取 `incoming/` 中的新文件；
2. 抽取文本和基础元数据；
3. 更新 `literature-library/papers.json`；
4. 重建 `literature-library/index.html`；
5. 将原文复制到 `literature-library/files/`；
6. 将已处理原文移动到 `processed/`；
7. 若部署开启，则自动 `rsync` 到远端网站。

#### 步骤 3：本地预览
```bash
python3 scripts/start_library_server.py
```
访问：
```text
http://127.0.0.1:8765/index.html
```

### 方案 B：双击启动（适合日常使用）
直接双击：
- `启动文献库.command`

它会依次执行：
1. `python3 scripts/update_library.py`
2. `python3 scripts/start_library_server.py`

## 五、监听模式工作流

适合：想把文献扔进投递箱后自动处理。

### 使用方式
双击：
- `启动监听.command`

或手动执行：
```bash
cd ~/Desktop/文献管理html
python3 scripts/watch_inbox.py
```

然后把文件放进：
```bash
~/Desktop/文献管理html/inbox/
```

监听脚本会：
1. 发现新文件；
2. 把文件移到 `incoming/`；
3. 调用 `update_library.py`；
4. 成功后保留处理结果；
5. 失败时尝试把文件移回 `inbox/`。

## 六、这次排查发现并修复的问题

### 路径错误 bug（已修复）
历史监听脚本写成了：
```text
~/Desktop/文献管理 html
```
但实际目录是：
```text
~/Desktop/文献管理html
```

受影响文件：
- `scripts/watch_inbox.py`
- `启动监听.command`

这会导致监听模式找错目录、无法正常工作。

**2026-03-28 已修复。**

## 七、如何判断系统是否正常

### 本地正常的标志
- `python3 scripts/update_library.py` 能正常输出 JSON 报告；
- `failures` 为空或只有个别不可解析文件；
- `literature-library/index.html` 已更新；
- `papers.json` 中篇目数正常；
- 本地可打开 `http://127.0.0.1:8765/index.html`。

### 远端正常的标志
`update_library.py` 输出中出现：
```json
"auto_sync": {
  "enabled": true,
  "ok": true
}
```

如果失败，优先检查：
1. SSH 免密是否还在；
2. 服务器是否在线；
3. `rsync` 是否可用；
4. 远端目录 `/var/www/literature-library/` 权限是否正确；
5. `caddy` 是否可 reload。

## 八、最小恢复步骤（给下一任小龙虾）

如果刚接班，什么都别猜，直接按下面走：

```bash
cd ~/Desktop/文献管理html
python3 scripts/update_library.py
python3 scripts/start_library_server.py
```

然后看 `update_library.py` 的输出：
- 如果 `auto_sync.ok = true`，说明网站同步也正常；
- 如果只是本地成功、远端失败，先别乱改脚本，优先检查 SSH / 服务器状态。

## 九、如果需要重新部署

只有在以下情况才算“需要重做”：
- `deploy_config.json` 丢失；
- SSH 免密失效且无法恢复；
- 远端网站目录结构被破坏；
- 服务器侧 Caddy / Web 根目录发生变化。

当前来看，**还没到这一步**。

## 十、建议的后续增强

建议后续补上：
1. 一个 `HEALTHCHECK.md` 或 `STATUS.md`，记录最近一次成功部署时间；
2. 一个 `requirements.txt`，明确 `pypdf` 等依赖；
3. 一个测试脚本，用于只校验部署链路、不重建全量内容；
4. 在首页显示“最近更新时间”，方便判断同步是否生效。

## 十一、2026-03-28 接管结论

- 已找到把文献管理系统推到个人网站的明确记录；
- 已确认自动同步链路目前仍可用；
- 已修复监听模式目录写错的 bug；
- 已补写本恢复指南，后续即使小龙虾猝死，也能较快恢复。
