# 联调冒烟步骤

## 1. 启动服务

- 后端: `cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000`
- 前端: `cd frontend && pnpm dev`

## 2. 登录流程

- 打开前端首页
- 使用 `admin / Admin@1234!` 登录
- 预期进入工作台页面

## 3. Token 刷新

- 登录后删除内存中的 access token 或等待 access token 过期
- 发起一个需要鉴权的接口请求
- 预期前端自动调用 `/api/auth/refresh`，请求重放成功

## 4. 权限不足

- 创建只读用户并分配 `viewer` 角色
- 登录只读用户
- 进入用户管理页后尝试执行“创建用户/批量启用/分配角色”
- 预期按钮隐藏或接口返回 403 并跳转无权限页面

## 5. 监控接口

- 访问 `/api/health`
- 访问 `/api/metrics`
- 预期返回数据库状态与响应时间统计
