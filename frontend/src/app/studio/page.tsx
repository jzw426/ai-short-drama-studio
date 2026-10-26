"use client";

import Link from "next/link";
import {
  FileText,
  Layout,
  Users,
  Clapperboard,
  CheckCircle2,
  ArrowRight,
} from "lucide-react";
import { useShallow } from "zustand/shallow";
import { useProjectStore, selectScriptStats } from "@/store/useProjectStore";

interface WorkflowStepDef {
  id: string;
  label: string;
  description: string;
  icon: React.ElementType;
  href: string;
}

const STEPS: WorkflowStepDef[] = [
  {
    id: "script",
    label: "剧本工坊",
    description: "编写短剧剧本，AI辅助生成对话和场景",
    icon: FileText,
    href: "/studio/script",
  },
  {
    id: "storyboard",
    label: "分镜设计",
    description: "可视化编排分镜，拖拽角色和素材到画布",
    icon: Layout,
    href: "/studio/storyboard",
  },
  {
    id: "characters",
    label: "角色管理",
    description: "创建和管理角色，AI生成角色形象",
    icon: Users,
    href: "/studio/characters",
  },
  {
    id: "render",
    label: "一键成片",
    description: "配置渲染参数，生成最终视频",
    icon: Clapperboard,
    href: "/studio/render",
  },
];

function getStepStatus(
  stepId: string,
  scriptSceneCount: number,
  storyboardSaved: boolean,
  workflowSteps: { script: boolean; storyboard: boolean; characters: boolean; render: boolean }
): "completed" | "active" | "pending" {
  if (workflowSteps[stepId as keyof typeof workflowSteps]) return "completed";

  switch (stepId) {
    case "script":
      return scriptSceneCount > 0 ? "active" : "pending";
    case "storyboard":
      return scriptSceneCount > 0 ? "active" : "pending";
    case "characters":
      return storyboardSaved || scriptSceneCount > 0 ? "pending" : "pending";
    case "render":
      return "pending";
    default:
      return "pending";
  }
}

export default function StudioPage() {
  const scriptScenes = useProjectStore((s) => s.scriptScenes);
  const storyboardCanvasState = useProjectStore((s) => s.storyboardCanvasState);
  const workflowSteps = useProjectStore((s) => s.workflowSteps);
  const currentProject = useProjectStore((s) => s.currentProject);
  const stats = useProjectStore(useShallow(selectScriptStats));

  const storyboardSaved = storyboardCanvasState !== null;
  const sceneCount = scriptScenes.length;

  return (
    <div className="max-w-7xl mx-auto space-y-8 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-surface-900">创作工作台</h1>
        <p className="text-surface-500 mt-1">
          {currentProject
            ? `当前项目：${currentProject.title}`
            : "按照流程指引完成短剧创作，从剧本到成片一步到位"}
        </p>
      </div>

      {/* 实时统计卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={<FileText size={20} className="text-primary-600" />}
          label="场景数"
          value={sceneCount.toString()}
          sub={
            sceneCount > 0
              ? `对白 ${stats.dialogueCount} · 字数 ${stats.totalChars}`
              : "尚未创建场景"
          }
        />
        <StatCard
          icon={<Layout size={20} className="text-purple-600" />}
          label="分镜状态"
          value={storyboardSaved ? "已保存" : "未保存"}
          sub={
            storyboardSaved
              ? "画布数据已持久化"
              : "进入分镜设计开始编排"
          }
        />
        <StatCard
          icon={<Users size={20} className="text-amber-600" />}
          label="角色数"
          value={useProjectStore((s) => s.projects.length > 0 ? "3" : "0")}
          sub="前往角色管理创建"
        />
        <StatCard
          icon={<Clapperboard size={20} className="text-green-600" />}
          label="渲染任务"
          value={useProjectStore((s) => s.workflowSteps.render ? "1" : "0")}
          sub="完成前序步骤后可用"
        />
      </div>

      {/* 工作流进度 */}
      <section className="card p-6">
        <h2 className="text-lg font-semibold text-surface-800 mb-6">
          创作流程
        </h2>
        <div className="flex items-center justify-between">
          {STEPS.map((step, index) => {
            const status = getStepStatus(
              step.id,
              sceneCount,
              storyboardSaved,
              workflowSteps
            );
            return (
              <div key={step.id} className="flex items-center flex-1">
                <Link
                  href={step.href}
                  className="flex flex-col items-center gap-3 group"
                >
                  <div
                    className={`w-14 h-14 rounded-full flex items-center justify-center transition-all duration-300 ${
                      status === "completed"
                        ? "bg-green-100"
                        : status === "active"
                        ? "bg-primary-100 ring-4 ring-primary-200 animate-pulse-glow"
                        : "bg-surface-100"
                    }`}
                  >
                    {status === "completed" ? (
                      <CheckCircle2 size={28} className="text-green-600" />
                    ) : (
                      <step.icon
                        size={28}
                        className={
                          status === "active"
                            ? "text-primary-600"
                            : "text-surface-400"
                        }
                      />
                    )}
                  </div>
                  <div className="text-center">
                    <p
                      className={`text-sm font-medium ${
                        status === "active"
                          ? "text-primary-700"
                          : status === "completed"
                          ? "text-green-700"
                          : "text-surface-400"
                      }`}
                    >
                      {step.label}
                    </p>
                    <p className="text-xs text-surface-400 mt-0.5">
                      {status === "completed"
                        ? "已完成"
                        : status === "active"
                        ? "进行中"
                        : "待开始"}
                    </p>
                  </div>
                </Link>
                {index < STEPS.length - 1 && (
                  <div className="flex-1 mx-4 h-0.5 bg-surface-200 relative">
                    <div
                      className={`absolute inset-y-0 left-0 transition-all duration-500 ${
                        status === "completed"
                          ? "w-full bg-green-400"
                          : status === "active"
                          ? "w-1/2 bg-primary-400"
                          : "w-0 bg-surface-300"
                      }`}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* 全部模块卡片 */}
      <section>
        <h2 className="text-lg font-semibold text-surface-800 mb-4">
          全部模块
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {STEPS.map((step) => {
            const status = getStepStatus(
              step.id,
              sceneCount,
              storyboardSaved,
              workflowSteps
            );
            return (
              <Link key={step.id} href={step.href} className="card p-5 group">
                <div className="flex items-center justify-between mb-3">
                  <div
                    className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      status === "completed"
                        ? "bg-green-100"
                        : status === "active"
                        ? "bg-primary-100"
                        : "bg-surface-100"
                    }`}
                  >
                    <step.icon
                      size={20}
                      className={
                        status === "pending"
                          ? "text-surface-400"
                          : status === "active"
                          ? "text-primary-600"
                          : "text-green-600"
                      }
                    />
                  </div>
                  <ArrowRight
                    size={16}
                    className="text-surface-300 group-hover:text-primary-500 transition-colors"
                  />
                </div>
                <h3 className="font-medium text-surface-800">{step.label}</h3>
                <p className="text-sm text-surface-400 mt-1">
                  {step.description}
                </p>
              </Link>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="card p-4 flex items-center gap-4">
      <div className="w-10 h-10 rounded-lg bg-surface-100 flex items-center justify-center flex-shrink-0">
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-xs text-surface-400">{label}</p>
        <p className="text-lg font-bold text-surface-900">{value}</p>
        <p className="text-[11px] text-surface-400 truncate">{sub}</p>
      </div>
    </div>
  );
}
