# 前端架构边界

## 入口划分

- `frontend/src` 是桌面端主应用入口，使用 Vue + Vite 构建，负责后台管理、角色权限、生产/库存/发货/质量等业务页面。
- `public/mobile*.html` 是移动扫码入口，面向扫码报工、抽检提交等现场流程，当前仍保留为轻量页面。
- `public/index.html`、`modules/routes/index-v2.html` 等旧入口仅作为兼容遗留入口，不应再承载新的后台管理功能。

## 权限目录来源

- 后端 `modules/permission_catalog.py` 是页面显示权限和业务操作权限的唯一目录来源。
- 前端 `frontend/src/lib/permissions.js` 只保留运行时缓存和离线回退，不再作为权限目录的主定义。
- 页面侧栏、路由守卫、设置页 Tab 统一通过 `frontend/src/composables/usePageAccess.js` 读取权限目录。

## 新功能落点规则

- 新增后台管理页面时，先扩展后端权限目录，再在 Vue 路由映射中接入组件。
- 新增移动扫码页面时，应优先复用已有 `/api/scan-*`、`/api/quality-*` 接口，避免把业务规则写进静态 HTML。
- 如果必须保留 legacy 页面兼容，需在本文档记录入口用途和迁移计划。
