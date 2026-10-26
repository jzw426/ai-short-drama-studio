# 后端环境配置指南

## 问题总结

### ❌ 尝试过的方法（均失败）

1. **使用Python 3.13 + 最新依赖**
   - 问题：`pydantic-core`需要Rust编译器
   - 错误：`No module named 'pydantic_core._pydantic_core'`

2. **使用Python 3.12 + 最新依赖**
   - 问题：同样需要Rust编译
   - 沙箱阻止访问`C:\Users\jiangzewen\AppData\Local\puccinialin`

3. **使用Python 3.13 + pydantic v1**
   - 问题：Python 3.13改变了`typing.ForwardRef._evaluate()`签名
   - 错误：`ForwardRef._evaluate() missing 1 required keyword-only argument: 'recursive_guard'`

4. **使用SQLite替代PostgreSQL**
   - 问题：pydantic v1与FastAPI 0.104.1在Python 3.13上不兼容

---

## ✅ 推荐解决方案：使用Docker Compose

### 步骤1：安装Docker Desktop
1. 下载：https://www.docker.com/products/docker-desktop/
2. 安装并启动Docker Desktop
3. 验证：`docker --version`

### 步骤2：启动项目
```bash
cd E:\ai-short-drama-studio
docker-compose up -d
```

### 步骤3：验证服务
```bash
# 检查容器状态
docker-compose ps

# 查看后端日志
docker-compose logs backend

# 查看前端日志
docker-compose logs frontend
```

### 步骤4：访问应用
- 前端：http://localhost:3000
- 后端API文档：http://localhost:8000/docs
- MinIO控制台：http://localhost:9001 (minioadmin/minioadmin)

---

## 🔧 替代方案：手动配置兼容环境

如果无法使用Docker，需要：

1. **安装Python 3.11**（与pydantic v1兼容）
   - 下载：https://www.python.org/downloads/release/python-3119/

2. **创建虚拟环境**
   ```bash
   cd E:\ai-short-drama-studio\backend
   C:\Python311\python.exe -m venv venv
   ```

3. **安装依赖**
   ```bash
   venv\Scripts\pip.exe install -r requirements-sqlite.txt
   ```

4. **修改代码以兼容pydantic v1**
   - 需要修改`app/main.py`和所有API路由
   - 这可能需要2-3天工作量

---

## 📋 当前状态

- ✅ 前端构建成功（Next.js 14.2.18）
- ⚠️ 后端环境配置中（需要Docker或Python 3.11）
- ⏳ 测试基础设施待创建

---

**建议**：优先使用Docker Compose方案，可以避免所有环境配置问题。

**文档更新**：2026-06-12
**负责人**：Senior Developer (高级开发工程师)
