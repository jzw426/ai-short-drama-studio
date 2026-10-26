"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import {
  Search,
  Bell,
  Settings,
  User,
  ChevronDown,
  LogOut,
} from "lucide-react";
import { getUser, clearAuth } from "@/lib/auth";
import { authApi } from "@/lib/api";

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const user = getUser();

  // 面包屑生成
  const segments = pathname.split("/").filter(Boolean);
  const breadcrumbs = segments.map((seg, index) => ({
    label: seg === "studio" ? "创作工作台" : seg,
    href: "/" + segments.slice(0, index + 1).join("/"),
    isLast: index === segments.length - 1,
  }));

  const handleLogout = async () => {
    try {
      // 清除服务端 httpOnly 会话 Cookie
      await authApi.logout();
    } catch {
      // 即使服务端失败也继续本地清理
    }
    clearAuth();
    router.replace("/login");
  };

  return (
    <header className="h-16 border-b border-surface-200 bg-white flex items-center justify-between px-6 shrink-0">
      {/* 左边：面包屑 + 搜索 */}
      <div className="flex items-center gap-6">
        {/* 面包屑 */}
        <nav className="flex items-center gap-2 text-sm">
          <Link href="/" className="text-primary-600 hover:text-primary-700 font-medium">
            AI Short Drama Studio
          </Link>
          {breadcrumbs.map((crumb) => (
            <span key={crumb.href} className="flex items-center gap-2">
              <span className="text-surface-300">/</span>
              {crumb.isLast ? (
                <span className="text-surface-800">{crumb.label}</span>
              ) : (
                <Link
                  href={crumb.href}
                  className="text-surface-500 hover:text-surface-700"
                >
                  {crumb.label}
                </Link>
              )}
            </span>
          ))}
        </nav>

        {/* 快捷搜索 */}
        <div className="relative hidden md:block">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400"
          />
          <input
            type="text"
            placeholder="搜索项目、剧本、角色..."
            className="w-64 pl-9 pr-3 py-1.5 text-sm border border-surface-200 rounded-lg bg-surface-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
          />
        </div>
      </div>

      {/* 右边：操作图标 + 用户 */}
      <div className="flex items-center gap-2">
        <button className="p-2 rounded-lg hover:bg-surface-100 text-surface-500 hover:text-surface-700 transition-colors relative">
          <Bell size={20} />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full" />
        </button>
        <button className="p-2 rounded-lg hover:bg-surface-100 text-surface-500 hover:text-surface-700 transition-colors">
          <Settings size={20} />
        </button>
        <div className="w-px h-6 bg-surface-200 mx-1" />

        {/* 用户菜单 */}
        <div className="relative">
          <div
            className="flex items-center gap-2 cursor-pointer hover:bg-surface-50 px-2 py-1 rounded-lg"
            onClick={() => setUserMenuOpen((v) => !v)}
          >
            <div className="w-8 h-8 bg-primary-100 rounded-full flex items-center justify-center">
              <User size={16} className="text-primary-600" />
            </div>
            <span className="text-sm text-surface-700 hidden sm:block">
              {user?.display_name || user?.username || "创作者"}
            </span>
            <ChevronDown size={14} className="text-surface-400" />
          </div>

          {userMenuOpen && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={() => setUserMenuOpen(false)}
              />
              <div className="absolute right-0 top-full mt-2 z-20 w-44 bg-white border border-surface-200 rounded-lg shadow-lg py-1">
                <div className="px-3 py-2 border-b border-surface-100">
                  <div className="text-sm font-medium text-surface-800">
                    {user?.display_name || "创作者"}
                  </div>
                  <div className="text-xs text-surface-400 truncate">
                    @{user?.username}
                  </div>
                </div>
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                >
                  <LogOut size={14} />
                  退出登录
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
