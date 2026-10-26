"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clapperboard,
  FileText,
  Layout,
  Loader2,
  RefreshCw,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import {
  characterApi,
  renderApi,
  scriptApi,
  storyboardApi,
  type CharacterDto,
  type RenderTaskDto,
  type SceneDto,
  type ScriptDto,
  type ShotDto,
} from "@/lib/api";
import { useCurrentProject } from "@/lib/useCurrentProject";

interface WorkflowStepDef {
  id: "script" | "storyboard" | "characters" | "render";
  label: string;
  description: string;
  icon: React.ElementType;
  href: string;
  count: number;
  done: boolean;
  summary: string;
}

const STEP_META: Omit<WorkflowStepDef, "count" | "done" | "summary">[] = [
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

const RENDER_STATUS_LABEL: Record<RenderTaskDto["status"], string> = {
  queued: "排队中",
  processing: "渲染中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export default function StudioPage() {
  const { project, loading: projectLoading, error: projectError } = useCurrentProject();
  const projectId = project?.id ?? null;

  const [scenes, setScenes] = useState<SceneDto[]>([]);
  const [shots, setShots] = useState<ShotDto[]>([]);
  const [characters, setCharacters] = useState<CharacterDto[]>([]);
  const [renderTasks, setRenderTasks] = useState<RenderTaskDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const [script, shotList, characterList, tasks] = await Promise.all([
        scriptApi.get(projectId) as Promise<unknown>,
        storyboardApi.listShots(projectId) as Promise<unknown>,
        characterApi.list(projectId) as Promise<unknown>,
        renderApi.list(projectId) as Promise<unknown>,
      ]);
      const scriptDto = script as ScriptDto | null;
      setScenes(Array.isArray(scriptDto?.scenes) ? scriptDto!.scenes : []);
      setShots(Array.isArray(shotList) ? (shotList as ShotDto[]) : []);
      setCharacters(
        Array.isArray(characterList) ? (characterList as CharacterDto[]) : []
      );
      setRenderTasks(Array.isArray(tasks) ? (tasks as RenderTaskDto[]) : []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "加载项目统计失败";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (projectId) void load();
    else {
      setScenes([]);
      setShots([]);
      setCharacters([]);
      setRenderTasks([]);
      setError(null);
    }
  }, [projectId, load]);

  const scriptStats = useMemo(() => {
    let dialogueCount = 0;
    let chars = 0;
    for (const scene of scenes) {
      dialogueCount += scene.dialogue
        .split(/\n+/)
        .map((line) => line.trim())
        .filter(Boolean).length;
      chars += Array.from(
        `${scene.title}${scene.location}${scene.summary}${scene.content}${scene.dialogue}`
      ).length;
    }
    return { dialogueCount, chars };
  }, [scenes]);

  const completedRenderCount = renderTasks.filter((t) => t.status === "completed").length;
  const latestRender = renderTasks[0];

  const steps: WorkflowStepDef[] = useMemo(() => {
    const values: Record<WorkflowStepDef["id"], { count: number; done: boolean; summary: string }> = {
      script: {
        count: scenes.length,
        done: scenes.length > 0,
        summary:
          scenes.length > 0
            ? `对白 ${scriptStats.dialogueCount} 条 · 字数 ${scriptStats.chars}`
            : "尚未创建场景",
      },
      storyboard: {
        count: shots.length,
        done: shots.length > 0,
        summary: shots.length > 0 ? `共 ${shots.length} 个镜头` : "尚未生成镜头",
      },
      characters: {
        count: characters.length,
        done: characters.length > 0,
        summary: characters.length > 0 ? `共 ${characters.length} 个角色` : "前往角色管理创建",
      },
      render: {
        count: renderTasks.length,
        done: completedRenderCount > 0,
        summary:
          latestRender != null
            ? `最近任务：${RENDER_STATUS_LABEL[latestRender.status] ?? latestRender.status}`
            : "尚未提交渲染",
      },
    };
    return STEP_META.map((meta) => ({ ...meta, ...values[meta.id] }));
  }, [scenes.length, shots.length, characters.length, scriptStats, renderTasks.length, completedRenderCount, latestRender]);

  const firstIncomplete = steps.find((s) => !s.done)?.id ?? null;

  const getStepStatus = (step: WorkflowStepDef): "completed" | "active" | "pending" => {
    if (step.done) return "completed";
    if (step.id === firstIncomplete) return "active";
    return "pending";
  };

  const isInitialLoading = loading && scenes.length === 0 && shots.length === 0 && characters.length === 0;

  if (!project) {
    return (
      <div className="max-w-3xl mx-auto mt-20 card p-10 text-center space-y-4">
        <FileText size={36} className="mx-auto text-surface-300" />
        <p className="text-surface-500">
          {projectLoading
            ? "正在加载项目列表…"
            : projectError ?? "先在首页新建或选择一个项目，再开始创作。"}
        </p>
        <Link href="/" className="btn-primary inline-flex">
          去选择项目
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-8 animate-fade-in">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">创作工作台</h1>
          <p className="text-surface-500 mt-1">当前项目：{project.title}</p>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="btn-outline flex items-center gap-1.5 text-sm disabled:opacity-60"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          刷新
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => void load()} className="text-xs underline">
            重试
          </button>
        </div>
      )}

      {/* 实时统计卡片 */}
      {isInitialLoading ? (
        <div className="card p-8 flex items-center justify-center gap-2 text-sm text-surface-500">
          <Loader2 size={16} className="animate-spin" />
          正在统计项目数据…
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {steps.map((step) => (
            <StatCard
              key={step.id}
              icon={<step.icon size={20} className="text-primary-600" />}
              label={
                step.id === "script"
                  ? "场景数"
                  : step.id === "storyboard"
                  ? "镜头数"
                  : step.id === "characters"
                  ? "角色数"
                  : "渲染任务"
              }
              value={String(step.count)}
              sub={step.summary}
            />
          ))}
        </div>
      )}

      {/* 工作流进度 */}
      <section className="card p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold text-surface-800">创作流程</h2>
          <Link href="/" className="text-xs text-surface-400 hover:text-primary-600">
            切换项目
          </Link>
        </div>
        <div className="flex items-center justify-between">
          {steps.map((step, index) => {
            const status = getStepStatus(step);
            return (
              <div key={step.id} className="flex items-center flex-1">
                <Link href={step.href} className="flex flex-col items-center gap-3 group">
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
                          status === "active" ? "text-primary-600" : "text-surface-400"
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
                {index < steps.length - 1 && (
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
        <h2 className="text-lg font-semibold text-surface-800 mb-4">全部模块</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {steps.map((step) => {
            const status = getStepStatus(step);
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
                <p className="text-sm text-surface-400 mt-1">{step.description}</p>
                <p className="text-xs text-surface-500 mt-2">{step.summary}</p>
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
