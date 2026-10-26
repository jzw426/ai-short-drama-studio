"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Play,
  FileText,
  Layout,
  Users,
  Clapperboard,
  FolderOpen,
  Plus,
  Clock,
  Loader2,
} from "lucide-react";
import { projectApi } from "@/lib/api";
import { useProjectStore } from "@/store/useProjectStore";
import type { Project } from "@/types";

const quickActions = [
  {
    title: "新建剧本",
    description: "从零开始创作剧本，支持AI辅助生成",
    icon: FileText,
    href: "/studio/script",
    color: "bg-blue-500",
  },
  {
    title: "分镜设计",
    description: "可视化编排分镜，拖拽角色到场景",
    icon: Layout,
    href: "/studio/storyboard",
    color: "bg-purple-500",
  },
  {
    title: "角色管理",
    description: "创建和管理AI角色，批量生成形象",
    icon: Users,
    href: "/studio/characters",
    color: "bg-green-500",
  },
  {
    title: "一键成片",
    description: "配置渲染参数，异步生成短剧视频",
    icon: Clapperboard,
    href: "/studio/render",
    color: "bg-orange-500",
  },
  {
    title: "素材库",
    description: "管理图片、音频、视频素材",
    icon: FolderOpen,
    href: "/studio/assets",
    color: "bg-pink-500",
  },
];

const statusLabels: Record<string, string> = {
  draft: "草稿",
  editing: "编辑中",
  rendering: "渲染中",
  completed: "已完成",
};

const statusStyles: Record<string, string> = {
  draft: "bg-surface-100 text-surface-600",
  editing: "bg-blue-100 text-blue-700",
  rendering: "bg-yellow-100 text-yellow-700",
  completed: "bg-green-100 text-green-700",
};

export default function Home() {
  const router = useRouter();
  const projects = useProjectStore((s) => s.projects);
  const setProjects = useProjectStore((s) => s.setProjects);
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载当前用户项目
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = (await projectApi.list()) as unknown as Project[];
        if (!cancelled) setProjects(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载项目失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setProjects]);

  // 新建项目并进入工作台
  const handleCreate = async () => {
    setCreating(true);
    try {
      const project = (await projectApi.create({
        title: `新项目 ${new Date().toLocaleDateString("zh-CN")}`,
      })) as unknown as Project;
      setCurrentProject(project);
      router.push("/studio");
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建项目失败");
    } finally {
      setCreating(false);
    }
  };

  const openProject = (project: Project) => {
    setCurrentProject(project);
    router.push("/studio");
  };

  return (
    <div className="max-w-7xl mx-auto space-y-8 animate-fade-in">
      {/* 欢迎区 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">
            欢迎回来，创作者
          </h1>
          <p className="text-surface-500 mt-1">
            从这里开始你的AI短剧创作之旅
          </p>
        </div>
        <button
          onClick={handleCreate}
          disabled={creating}
          className="btn-primary flex items-center gap-2 disabled:opacity-60"
        >
          {creating ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <Plus size={18} />
          )}
          {creating ? "创建中..." : "新建项目"}
        </button>
      </div>

      {/* 快捷入口 */}
      <section>
        <h2 className="text-lg font-semibold text-surface-800 mb-4">
          快捷入口
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {quickActions.map((action) => (
            <Link
              key={action.title}
              href={action.href}
              className="card p-5 hover:border-primary-300 group"
            >
              <div
                className={`${action.color} w-10 h-10 rounded-lg flex items-center justify-center mb-3`}
              >
                <action.icon size={20} className="text-white" />
              </div>
              <h3 className="font-medium text-surface-800 group-hover:text-primary-700 transition-colors">
                {action.title}
              </h3>
              <p className="text-sm text-surface-400 mt-1">
                {action.description}
              </p>
            </Link>
          ))}
        </div>
      </section>

      {/* 最近项目（真实数据） */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-surface-800">我的项目</h2>
          <Link
            href="/studio"
            className="text-sm text-primary-600 hover:text-primary-700"
          >
            进入工作台 →
          </Link>
        </div>

        {error && (
          <div className="card p-4 text-sm text-red-600 bg-red-50 border-red-200">
            {error}
          </div>
        )}

        {loading ? (
          <div className="card p-8 flex items-center justify-center text-surface-400">
            <Loader2 size={20} className="animate-spin mr-2" />
            加载项目中...
          </div>
        ) : projects.length === 0 ? (
          <div className="card p-8 text-center text-surface-400">
            还没有项目，点击右上角「新建项目」开始创作
          </div>
        ) : (
          <div className="grid gap-3">
            {projects.map((project) => (
              <button
                key={project.id}
                onClick={() => openProject(project)}
                className="card p-4 flex items-center justify-between hover:border-primary-200 text-left w-full"
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-primary-100 flex items-center justify-center">
                    <Play size={20} className="text-primary-600" />
                  </div>
                  <div>
                    <h3 className="font-medium text-surface-800">
                      {project.title}
                    </h3>
                    <div className="flex items-center gap-2 mt-1">
                      <Clock size={14} className="text-surface-400" />
                      <span className="text-xs text-surface-400">
                        {new Date(project.updated_at).toLocaleString("zh-CN")}
                      </span>
                      <span
                        className={`text-xs px-2 py-0.5 rounded-full ${
                          statusStyles[project.status] || statusStyles.draft
                        }`}
                      >
                        {statusLabels[project.status] || "草稿"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* 进度条 */}
                <div className="flex items-center gap-3">
                  <div className="w-32 h-2 bg-surface-200 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        project.status === "completed"
                          ? "bg-green-500"
                          : project.status === "rendering"
                          ? "bg-yellow-500"
                          : "bg-primary-500"
                      }`}
                      style={{ width: `${project.progress || 0}%` }}
                    />
                  </div>
                  <span className="text-sm text-surface-500 w-10 text-right">
                    {project.progress || 0}%
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
