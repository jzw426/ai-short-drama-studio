"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { Navbar } from "@/components/Navbar";
import { isAuthenticated } from "@/lib/auth";

/**
 * 应用外壳：
 * - 登录页（/login）只渲染内容，不显示工作台布局
 * - 其他页面若未登录则跳转登录页（路由守卫）
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLoginPage = pathname.startsWith("/login");
  const [ready, setReady] = useState(isLoginPage);

  useEffect(() => {
    if (!isLoginPage && !isAuthenticated()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [isLoginPage, router]);

  if (isLoginPage) return <>{children}</>;

  // 守卫检查完成前不渲染，避免未登录内容闪烁
  if (!ready) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Navbar />
        <main className="flex-1 overflow-y-auto p-6 scrollbar-thin">
          {children}
        </main>
      </div>
    </div>
  );
}
