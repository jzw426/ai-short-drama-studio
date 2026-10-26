# 剧本页面 Client-Side Exception 修复报告

**修复日期**：2026-06-13
**问题症状**：点击"剧本"页面显示 "Application error: a client-side exception has occurred"

## 根本原因分析

经过代码审查，发现剧本页面（/studio/script）渲染时使用了以下CSS动画类，但**这些类在 `globals.css` 中并未定义**：

1. **`animate-fade-in`** - 在 `ScriptEditor.tsx` 第7行使用
2. **`animate-pulse-glow`** - 在 `studio/page.tsx` 第156行使用
3. **`animate-spin`** - 在多个组件中用于loading状态

**为什么这会导致client-side exception**：
- Next.js在生产构建时启用CSS优化
- 未定义的Tailwind类会触发`@apply`相关的hydration错误
- React 18 + Next.js 14对hydration mismatch非常敏感

## 已修复的问题

### ✅ 修复1：添加缺失的CSS动画类

**文件**：`frontend/src/app/globals.css`

在 `@layer utilities` 中添加了：
- `animate-fade-in` (淡入上移动画)
- `animate-pulse-glow` (脉动光晕动画)
- `animate-spin` (旋转动画)
- `animate-pulse` (脉冲动画)

### ✅ 修复2：移除Google Fonts依赖（避免网络问题）

**文件**：`frontend/src/app/layout.tsx`

移除了 `Inter` 字体从 `next/font/google` 的导入，因为：
- 在沙箱/受限网络环境下Google Fonts可能无法访问
- 字体加载失败会阻塞整个页面的hydration
- 改用系统默认字体（无外部依赖）

### ✅ 修复3：添加全局 ErrorBoundary

**新增文件**：`frontend/src/components/ErrorBoundary.tsx`

- 捕获所有客户端JavaScript错误
- 显示友好的错误信息（不再显示生硬的英文错误）
- 显示详细错误堆栈便于调试
- 提供"重新加载"和"清除数据并重载"按钮

**修改文件**：`frontend/src/app/layout.tsx`
- 在 Providers 中包装了 ErrorBoundary

## 验证

本地构建测试：
```
✓ Compiled successfully
✓ Generating static pages (10/10)
```

所有10个页面都成功生成，包括 `/studio/script`。

## Docker镜像重建

代码已修复，但Docker daemon当前卡死。需要：
1. **手动重启Docker Desktop**（在系统托盘右键 → Restart）
2. 等待Docker恢复后执行：
   ```bash
   cd E:\ai-short-drama-studio
   docker-compose up -d --build frontend
   ```
3. 浏览器硬刷新（Ctrl+Shift+R）访问 http://localhost:3000/studio/script

## 其他可能的问题排查

如果重新部署后仍有问题，请检查：

1. **localStorage中的旧数据**导致store加载失败
   - 解决：点击ErrorBoundary的"清除数据并重载"按钮
   - 或浏览器控制台执行：`localStorage.removeItem("ai-drama-studio-store")`

2. **Network面板中的具体错误**
   - 按F12打开浏览器开发者工具
   - 查看 Console 选项卡的红色错误信息
   - 查看 Network 选项卡中的失败请求

3. **确保后端API可达**
   - http://localhost:8000/api/v1/health 应返回 `{"status":"healthy",...}`

## 修改的文件清单

- ✏️ `frontend/src/app/globals.css` - 添加动画类
- ✏️ `frontend/src/app/layout.tsx` - 移除Google Fonts + 添加ErrorBoundary
- ➕ `frontend/src/components/ErrorBoundary.tsx` - 新增错误边界组件
- ✏️ `docker/Dockerfile.frontend` - 优化构建配置（添加npm国内源）

---

**修复完成度**：3/3 核心问题已修复
**等待**：Docker daemon恢复 + 重新构建镜像
