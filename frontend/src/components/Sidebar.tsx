"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  FileText,
  Layout,
  Users,
  Clapperboard,
  FolderOpen,
  ChevronRight,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { useState } from "react";

interface NavItem {
  label: string;
  icon: React.ElementType;
  href: string;
  badge?: string;
}

const mainNav: NavItem[] = [
  { label: "首页工作台", icon: Home, href: "/" },
];

const workflowNav: NavItem[] = [
  { label: "剧本工坊", icon: FileText, href: "/studio/script" },
  { label: "分镜设计", icon: Layout, href: "/studio/storyboard" },
  { label: "角色管理", icon: Users, href: "/studio/characters" },
  { label: "一键成片", icon: Clapperboard, href: "/studio/render" },
  { label: "素材库", icon: FolderOpen, href: "/studio/assets" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <aside
      className={`${
        collapsed ? "w-16" : "w-60"
      } h-full bg-surface-900 text-white flex flex-col transition-all duration-300 shrink-0`}
    >
      {/* Logo */}
      <div className="h-16 flex items-center justify-between px-4 border-b border-surface-700">
        {!collapsed && (
          <Link href="/" className="flex items-center gap-2">
            <Clapperboard size={22} className="text-primary-400" />
            <span className="font-bold text-sm">AI Drama Studio</span>
          </Link>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1.5 rounded-md hover:bg-surface-800 text-surface-400 hover:text-white transition-colors"
        >
          {collapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>

      {/* 导航菜单 */}
      <nav className="flex-1 py-4 px-2 space-y-6 overflow-y-auto scrollbar-thin">
        {/* 主页 */}
        <div>
          {!collapsed && (
            <p className="text-xs text-surface-500 uppercase tracking-wider px-3 mb-2">
              主页
            </p>
          )}
          {mainNav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg mb-1 transition-all ${
                isActive(item.href)
                  ? "bg-primary-600/30 text-primary-300"
                  : "text-surface-400 hover:bg-surface-800 hover:text-white"
              }`}
              title={collapsed ? item.label : undefined}
            >
              <item.icon size={20} />
              {!collapsed && (
                <>
                  <span className="text-sm flex-1">{item.label}</span>
                  {item.badge && (
                    <span className="text-xs bg-primary-600 px-1.5 py-0.5 rounded-full">
                      {item.badge}
                    </span>
                  )}
                </>
              )}
            </Link>
          ))}
        </div>

        {/* 创作工作流 */}
        <div>
          {!collapsed && (
            <p className="text-xs text-surface-500 uppercase tracking-wider px-3 mb-2">
              创作工作流
            </p>
          )}
          {workflowNav.map((item, index) => (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg mb-1 transition-all ${
                isActive(item.href)
                  ? "bg-primary-600/30 text-primary-300"
                  : "text-surface-400 hover:bg-surface-800 hover:text-white"
              }`}
              title={collapsed ? item.label : undefined}
            >
              <div className="relative">
                <item.icon size={20} />
                {index < workflowNav.length - 1 && !collapsed && (
                  <div className="absolute left-2.5 top-full w-px h-4 bg-surface-700" />
                )}
              </div>
              {!collapsed && (
                <span className="text-sm flex-1">{item.label}</span>
              )}
            </Link>
          ))}
        </div>
      </nav>

      {/* 底部版本信息 */}
      {!collapsed && (
        <div className="px-4 py-3 border-t border-surface-700">
          <p className="text-xs text-surface-500">v0.1.0 · AI Short Drama Studio</p>
          <p className="text-xs text-surface-600 mt-0.5">
            Powered by Kling + Seedance
          </p>
        </div>
      )}
    </aside>
  );
}
