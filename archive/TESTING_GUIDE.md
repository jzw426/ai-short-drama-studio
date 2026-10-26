# 测试基础设施设置指南

## 目标
为AI Short Drama Studio项目创建完整的测试框架，自动检测每个功能是否正常工作。

---

## 1. 前端测试框架（Jest + React Testing Library）

### 安装依赖
```bash
cd E:\ai-short-drama-studio\frontend
npm install -D jest @testing-library/react @testing-library/jest-dom @testing-library/user-event jest-environment-jsdom
```

### 配置文件：`jest.config.js`
```javascript
const nextJest = require('next/jest');

const createJestConfig = nextJest({
  dir: './',
});

const customJestConfig = {
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  testEnvironment: 'jest-environment-jsdom',
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  testPathIgnorePatterns: ['<rootDir>/node_modules/', '<rootDir>/.next/'],
};

module.exports = createJestConfig(customJestConfig);
```

### 设置文件：`jest.setup.js`
```javascript
import '@testing-library/jest-dom';
```

### 示例测试：`src/__tests__/Home.test.tsx`
```typescript
import { render, screen } from '@testing-library/react';
import Home from '@/app/page';

describe('Home Page', () => {
  it('renders welcome message', () => {
    render(<Home />);
    const heading = screen.getByText(/欢迎回来，创作者/);
    expect(heading).toBeInTheDocument();
  });

  it('shows quick action buttons', () => {
    render(<Home />);
    expect(screen.getByText('新建剧本')).toBeInTheDocument();
    expect(screen.getByText('分镜设计')).toBeInTheDocument();
    expect(screen.getByText('角色管理')).toBeInTheDocument();
  });
});
```

---

## 2. 后端测试框架（pytest）

### 安装依赖
```bash
cd E:\ai-short-drama-studio\backend
venv\Scripts\pip.exe install pytest pytest-asyncio httpx
```

### 配置文件：`pytest.ini`
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

### 示例测试：`tests/test_main.py`
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_read_main():
    response = client.get("/")
    assert response.status_code == 200
    assert "AI Short Drama Studio" in response.text

def test_api_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

---

## 3. 功能检测脚本（自动化验证）

### 脚本：`scripts/check_functionality.py`
```python
import requests
import sys

BASE_URL = "http://localhost:3000"

def check_page(url, name):
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            print(f"✅ {name} - OK")
            return True
        else:
            print(f"❌ {name} - Failed (status: {response.status_code})")
            return False
    except Exception as e:
        print(f"❌ {name} - Error: {e}")
        return False

def main():
    print("=" * 50)
    print("AI Short Drama Studio - 功能检测")
    print("=" * 50)
    
    pages = [
        ("/", "首页"),
        ("/studio", "工作台"),
        ("/studio/script", "剧本管理"),
        ("/studio/characters", "角色管理"),
        ("/studio/assets", "素材管理"),
        ("/studio/storyboard", "分镜编辑器"),
        ("/studio/render", "视频渲染"),
    ]
    
    results = []
    for url, name in pages:
        success = check_page(BASE_URL + url, name)
        results.append((name, success))
    
    print("\n" + "=" * 50)
    print("检测报告")
    print("=" * 50)
    
    success_count = sum(1 for _, success in results if success)
    total_count = len(results)
    
    for name, success in results:
        status = "✅ 正常" if success else "❌ 异常"
        print(f"{name}: {status}")
    
    print(f"\n总结：{success_count}/{total_count} 功能正常")
    
    if success_count < total_count:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
```

---

## 4. 运行测试

### 前端测试
```bash
cd E:\ai-short-drama-studio\frontend
npm run test  # 运行所有测试
npm run test -- --watch  # 监听模式
```

### 后端测试
```bash
cd E:\ai-short-drama-studio\backend
venv\Scripts\pytest.exe  # 运行所有测试
venv\Scripts\pytest.exe -v  # 详细模式
```

### 功能检测
```bash
cd E:\ai-short-drama-studio
python scripts/check_functionality.py
```

---

## 5. CI/CD集成（GitHub Actions示例）

### 文件：`.github/workflows/ci.yml`
```yaml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
          
      - name: Install frontend dependencies
        run: cd frontend && npm install
        
      - name: Run frontend tests
        run: cd frontend && npm run test
        
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
          
      - name: Install backend dependencies
        run: cd backend && pip install -r requirements.txt
        
      - name: Run backend tests
        run: cd backend && pytest
```

---

## 6. 下一步

1. ✅ 安装测试框架
2. ⏳ 编写单元测试（每个组件/API）
3. ⏳ 编写集成测试（用户流程）
4. ⏳ 配置CI/CD自动化

---

**创建日期**：2026-06-12  
**负责人**：Senior Developer (高级开发工程师)
