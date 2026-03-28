# 使用说明

## 1. 导入文献

将新文献复制到：

- `incoming/`

支持格式：

- PDF
- DOCX
- TXT
- Markdown
- HTML
- ZIP

## 2. 更新文献库

```bash
python3 scripts/update_library.py
```

该脚本会：

1. 解析待导入文献
2. 更新 `literature-library/papers.json`
3. 更新 `literature-library/index.html`
4. 将原文复制到 `literature-library/files/`
5. 将已处理原文归档到 `processed/`
6. 如果配置了远端发布，则自动尝试同步

## 3. 本地浏览

```bash
python3 scripts/start_library_server.py
```

打开：

- `http://127.0.0.1:8765/index.html`

## 4. 一键启动

直接双击：

- `启动文献库.command`
