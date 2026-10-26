"use client";

import { useState, useEffect } from "react";
import { RenderPanel } from "@/components/RenderPanel";
import {
  Play,
  Pause,
  RotateCcw,
  Download,
  Settings2,
  Clock,
} from "lucide-react";

interface RenderTask {
  id: string;
  name: string;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number;
  startTime?: string;
  outputUrl?: string;
  errorMessage?: string;
}

const demoTasks: RenderTask[] = [
  {
    id: "r1",
    name: "逆袭之都市风云·第一集",
    status: "completed",
    progress: 100,
    startTime: "2026-06-10 10:00",
    outputUrl: "",
  },
  {
    id: "r2",
    name: "古风奇缘·预告片",
    status: "processing",
    progress: 67,
    startTime: "2026-06-10 14:30",
  },
  {
    id: "r3",
    name: "AI觉醒日记·测试",
    status: "failed",
    progress: 45,
    startTime: "2026-06-09 16:00",
    errorMessage: "GPU 资源不足",
  },
];

const statusStyles: Record<string, string> = {
  queued: "bg-surface-100 text-surface-600",
  processing: "bg-yellow-100 text-yellow-700",
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

const statusLabels: Record<string, string> = {
  queued: "排队中",
  processing: "渲染中",
  completed: "已完成",
  failed: "失败",
};

export default function RenderPage() {
  const [tasks, setTasks] = useState<RenderTask[]>(demoTasks);
  const [selectedTask, setSelectedTask] = useState<RenderTask>(demoTasks[0]);
  const [isPlaying, setIsPlaying] = useState(false);

  // 模拟进度更新
  useEffect(() => {
    const interval = setInterval(() => {
      setTasks((prev) =>
        prev.map((t) =>
          t.status === "processing"
            ? { ...t, progress: Math.min(t.progress + 1, 99) }
            : t
        )
      );
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="max-w-7xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">一键成片</h1>
          <p className="text-surface-500 mt-1">渲染配置、异步任务管理、视频预览</p>
        </div>
        <div className="flex gap-3">
          <button className="btn-outline flex items-center gap-2">
            <Settings2 size={16} />
            渲染设置
          </button>
          <button className="btn-primary flex items-center gap-2">
            <Play size={16} />
            新建渲染任务
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* 左侧：任务列表 */}
        <div className="lg:col-span-1 space-y-3">
          <h3 className="font-medium text-surface-700">渲染任务</h3>
          <div className="space-y-2">
            {tasks.map((task) => (
              <div
                key={task.id}
                onClick={() => setSelectedTask(task)}
                className={`p-3 rounded-lg cursor-pointer border transition-all ${
                  selectedTask.id === task.id
                    ? "border-primary-500 bg-primary-50"
                    : "border-surface-200 hover:border-surface-300 bg-white"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-surface-800 truncate max-w-[160px]">
                    {task.name}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${statusStyles[task.status]}`}
                  >
                    {statusLabels[task.status]}
                  </span>
                </div>
                <div className="mt-2 w-full h-1.5 bg-surface-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${
                      task.status === "failed"
                        ? "bg-red-500"
                        : task.status === "completed"
                        ? "bg-green-500"
                        : "bg-primary-500"
                    }`}
                    style={{ width: `${task.progress}%` }}
                  />
                </div>
                <p className="text-xs text-surface-400 mt-1.5">
                  {task.progress}%{task.startTime ? ` · ${task.startTime.split(" ")[1]}` : ""}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* 右侧：渲染面板 */}
        <div className="lg:col-span-3 space-y-4">
          {/* 播放器预览区 */}
          <div className="card overflow-hidden">
            <div className="aspect-video bg-surface-900 flex items-center justify-center relative">
              {selectedTask.status === "completed" ? (
                <>
                  <div className="text-surface-400 text-center">
                    <Play size={48} className="mx-auto mb-2 opacity-50" />
                    <p className="text-sm">视频预览区域</p>
                    <p className="text-xs text-surface-500 mt-1">
                      实际接入后在此播放渲染完成的短剧视频
                    </p>
                  </div>
                  {/* 播放控制 */}
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-4 flex items-center gap-3">
                    <button
                      onClick={() => setIsPlaying(!isPlaying)}
                      className="text-white hover:text-primary-400 transition-colors"
                    >
                      {isPlaying ? <Pause size={20} /> : <Play size={20} />}
                    </button>
                    <div className="flex-1 h-1 bg-white/30 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary-500 rounded-full"
                        style={{ width: "35%" }}
                      />
                    </div>
                    <span className="text-xs text-white/70">01:24 / 03:30</span>
                    <button className="text-white/70 hover:text-white">
                      <Download size={16} />
                    </button>
                  </div>
                </>
              ) : selectedTask.status === "processing" ? (
                <div className="text-center">
                  <div className="w-16 h-16 border-4 border-primary-500 border-t-transparent rounded-full animate-spin mx-auto" />
                  <p className="text-surface-400 mt-4">
                    正在渲染中... {selectedTask.progress}%
                  </p>
                </div>
              ) : selectedTask.status === "failed" ? (
                <div className="text-center">
                  <p className="text-red-400 text-lg">渲染失败</p>
                  <p className="text-surface-500 text-sm mt-2">
                    请检查配置后重试
                  </p>
                  <button className="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg text-sm flex items-center gap-2 mx-auto">
                    <RotateCcw size={14} />
                    重新渲染
                  </button>
                </div>
              ) : (
                <div className="text-center">
                  <div className="w-16 h-16 bg-surface-700 rounded-full flex items-center justify-center mx-auto">
                    <Clock size={28} className="text-surface-400" />
                  </div>
                  <p className="text-surface-400 mt-4">等待渲染队列...</p>
                </div>
              )}
            </div>
          </div>

          {/* 渲染配置面板 */}
          <RenderPanel task={selectedTask} />
        </div>
      </div>
    </div>
  );
}
