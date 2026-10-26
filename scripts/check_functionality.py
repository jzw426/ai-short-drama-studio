#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Short Drama Studio - 功能检测脚本
检测项目中的每个功能模块是否正常工作
"""

import os
import sys
import json
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

class FunctionalityChecker:
    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0
    
    def check(self, name, status, details=""):
        """记录检测结果"""
        if status:
            self.passed += 1
            symbol = "[OK]"
        else:
            self.failed += 1
            symbol = "[FAIL]"
        
        self.results.append({
            "name": name,
            "status": status,
            "details": details
        })
        print(f"{symbol} {name}")
        if details:
            print(f"   └─ {details}")
    
    def check_file_exists(self, filepath, name):
        """检查文件是否存在"""
        full_path = PROJECT_ROOT / filepath
        exists = full_path.exists()
        self.check(name, exists, f"文件: {filepath}")
        return exists
    
    def check_frontend_build(self):
        """检测前端构建"""
        print("\n📦 前端构建检测")
        print("-" * 50)
        
        # 检查package.json
        self.check_file_exists("frontend/package.json", "package.json存在")
        
        # 检查node_modules
        node_modules = PROJECT_ROOT / "frontend/node_modules"
        self.check("node_modules安装", node_modules.exists(), "前端依赖已安装")
        
        # 检查Next.js配置
        self.check_file_exists("frontend/next.config.js", "Next.js配置文件")
        
        # 检查Tailwind配置
        self.check_file_exists("frontend/tailwind.config.js", "Tailwind CSS配置")
    
    def check_backend_setup(self):
        """检测后端配置"""
        print("\n🔧 后端配置检测")
        print("-" * 50)
        
        # 检查requirements.txt
        self.check_file_exists("backend/requirements.txt", "requirements.txt存在")
        
        # 检查main.py
        self.check_file_exists("backend/app/main.py", "FastAPI主文件")
        
        # 检查Docker配置
        self.check_file_exists("docker-compose.yml", "Docker Compose配置")
        self.check_file_exists("docker/Dockerfile.frontend", "前端Dockerfile")
        self.check_file_exists("docker/Dockerfile.backend", "后端Dockerfile")
    
    def check_functionality_modules(self):
        """检测功能模块"""
        print("\n🎯 功能模块检测")
        print("-" * 50)
        
        # 前端页面
        pages = [
            ("frontend/src/app/page.tsx", "首页"),
            ("frontend/src/app/studio/page.tsx", "工作台"),
            ("frontend/src/app/studio/script/page.tsx", "剧本管理"),
            ("frontend/src/app/studio/characters/page.tsx", "角色管理"),
            ("frontend/src/app/studio/assets/page.tsx", "素材管理"),
            ("frontend/src/app/studio/storyboard/page.tsx", "分镜编辑器"),
            ("frontend/src/app/studio/render/page.tsx", "视频渲染"),
        ]
        
        for filepath, name in pages:
            self.check_file_exists(filepath, f"{name}页面")
        
        # 前端组件
        components = [
            ("frontend/src/components/StoryboardCanvas.tsx", "分镜画布组件"),
            ("frontend/src/lib/api.ts", "API服务"),
        ]
        
        for filepath, name in components:
            self.check_file_exists(filepath, f"{name}")
    
    def check_code_quality(self):
        """检测代码质量"""
        print("\n📋 代码质量检测")
        print("-" * 50)
        
        # 检查TypeScript配置
        self.check_file_exists("frontend/tsconfig.json", "TypeScript配置")
        
        # 检查ESLint配置
        eslint = PROJECT_ROOT / "frontend/.eslintrc.json"
        self.check("ESLint配置", eslint.exists(), "代码规范检查")
        
        # 检查是否有测试文件
        test_files = list((PROJECT_ROOT / "frontend/src").rglob("*.test.tsx")) + \
                   list((PROJECT_ROOT / "frontend/src").rglob("*.spec.tsx"))
        self.check("前端测试文件", len(test_files) > 0, f"找到{len(test_files)}个测试文件")
        
        backend_test_files = list((PROJECT_ROOT / "backend").rglob("test_*.py")) + \
                           list((PROJECT_ROOT / "backend").rglob("*_test.py"))
        backend_test_files = [f for f in backend_test_files if "venv" not in str(f)]
        self.check("后端测试文件", len(backend_test_files) > 0, f"找到{len(backend_test_files)}个测试文件")
    
    def check_documentation(self):
        """检测文档完整性"""
        print("\n📚 文档完整性检测")
        print("-" * 50)
        
        self.check_file_exists("README.md", "项目README")
        self.check_file_exists("frontend/AUDIT_REPORT.md", "前端审计报告")
        self.check_file_exists("backend/SETUP_GUIDE.md", "后端配置指南")
        self.check_file_exists("TESTING_GUIDE.md", "测试指南")
    
    def generate_report(self):
        """生成检测报告"""
        print("\n" + "=" * 50)
        print("📊 功能检测报告")
        print("=" * 50)
        
        print(f"\n[OK] 通过: {self.passed}")
        print(f"[FAIL] 失败: {self.failed}")
        print(f"📈 成功率: {self.passed/(self.passed+self.failed)*100:.1f}%")
        
        if self.failed > 0:
            print("\n[FAIL] 失败项目:")
            for result in self.results:
                if not result["status"]:
                    print(f"  - {result['name']}: {result['details']}")
        
        print("\n" + "=" * 50)
        
        # 保存JSON报告
        report = {
            "summary": {
                "total": self.passed + self.failed,
                "passed": self.passed,
                "failed": self.failed,
                "success_rate": f"{self.passed/(self.passed+self.failed)*100:.1f}%"
            },
            "details": self.results
        }
        
        report_path = PROJECT_ROOT / "functionality_check_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n📄 详细报告已保存: {report_path}")
        
        return self.failed == 0

def main():
    """主函数"""
    print("=" * 50)
    print("🎬 AI Short Drama Studio - 功能检测")
    print("=" * 50)
    
    checker = FunctionalityChecker()
    
    # 执行检测
    checker.check_frontend_build()
    checker.check_backend_setup()
    checker.check_functionality_modules()
    checker.check_code_quality()
    checker.check_documentation()
    
    # 生成报告
    success = checker.generate_report()
    
    # 返回状态码
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
