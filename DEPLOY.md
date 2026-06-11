# 部署与回滚流程

## 当前运行方式：systemd（用户级服务）

服务由 systemd --user 管理，无需 root 权限，开机关机自动启停。


### 日常部署
```bash
cd /home/dubin/qr-system
git pull origin master          # 拉取最新代码
systemctl --user restart qr-system   # 重启服务（graceful）
curl -sk https://127.0.0.1:3000/api/auth/login -X POST -d '{"username":"admin","password":"123456"}' -H "Content-Type: application/json"  # 验证
```

### 服务管理命令
```bash
systemctl --user status qr-system    # 查看状态
systemctl --user restart qr-system   # 重启
systemctl --user stop qr-system      # 停止
systemctl --user start qr-system     # 启动
journalctl --user -u qr-system -f    # 实时日志
journalctl --user -u qr-system -n 50 # 最近50行日志
```

### 配置位置
- Unit 文件: `~/.config/systemd/user/qr-system.service`
- 自动重启: `Restart=always` (崩溃后10秒自动恢复)
- 内存限制: 512 MB
- 崩溃限制: 2分钟内最多重启5次

## 紧急回滚
```bash
cd /home/dubin/qr-system
git checkout v1.0.0             # 回到上一个稳定版本
systemctl --user restart qr-system
```

## 查看可用版本
```bash
git tag -l                      # 列出所有发布版本
git log --oneline --decorate    # 查看提交历史
```

## 备份恢复
```bash
# 恢复数据库
gunzip -c backups/db_YYYYMMDD_HHMMSS.sql.gz | sqlite3 data/production.db
systemctl --user restart qr-system
```
