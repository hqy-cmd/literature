# 远程部署说明

## 当前部署方式

- 远端服务器：Ubuntu 22.04
- Web 服务：Caddy
- 文献目录：`/var/www/literature-library/`
- 访问方式：HTTP + IP

## 本地自动同步配置

配置文件：

- `config/deploy_config.json`

示例：

```json
{
  "enabled": true,
  "host": "218.244.147.33",
  "user": "admin",
  "remote_path": "/var/www/literature-library/"
}
```

## 自动同步依赖

必须满足：

- 本地能通过 SSH 免密连接远端
- `rsync` 可用
- 远端用户具备修正文献目录权限并 reload caddy 的能力

当前脚本会在 `rsync` 完成后自动执行远端修复：

- 目录权限统一为 `755`
- 文件权限统一为 `644`
- `systemctl reload caddy`

测试命令：

```bash
ssh root@218.244.147.33
rsync -az --delete ~/Desktop/文献管理html/literature-library/ root@218.244.147.33:/var/www/literature-library/
```

## 如果自动同步失败

优先检查：

1. SSH 是否免密
2. 远端目录权限是否正确
3. Caddy 是否可读 `/var/www/literature-library`
