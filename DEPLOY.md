# 部署与回滚流程

## 日常部署
```bash
cd /home/dubin/qr-system
git pull origin master          # 拉取最新代码
pm2 restart qr-system           # 重启服务
curl -sk https://127.0.0.1:3000/api/auth/login -X POST -d '{username:admin,password:123456}' -H Content-Type: application/json  # 验证
```

## 紧急回滚
```bash
cd /home/dubin/qr-system
git checkout v1.0.0             # 回到上一个稳定版本
pm2 restart qr-system
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
pm2 restart qr-system
```
