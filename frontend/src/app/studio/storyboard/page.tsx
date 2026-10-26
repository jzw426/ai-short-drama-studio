"use client";

import { useState } from "react";
import { StoryboardCanvas } from "@/components/StoryboardCanvas";
import { Sparkles, Loader2 } from "lucide-react";
import { storyboardApi } from "@/lib/api";
import { useProjectStore } from "@/store/useProjectStore";

export default function StoryboardPage() {
  const currentProject = useProjectStore((s) => s.currentProject);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleGenerateFromScript = async () => {
    if (!currentProject) {
      setMessage("请先在首页新建或选择一个项目");
      return;
    }
    setGenerating(true);
    setMessage(null);
    try {
      const resp = (await storyboardApi.generateFromScript(
        currentProject.id
      )) as unknown as { status: string; total: number };
      setMessage(
        resp.status === "success"
          ? `已从剧本生成 ${resp.total} 个镜头（替换原有镜头）`
          : "生成失败，请重试"
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "生成失败，请重试");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="h-full flex flex-col animate-fade-in">
      <div className="flex items-center justify-between px-6 py-4 border-b border-surface-200 bg-white flex-shrink-0">
        <div>
          <h1 className="text-xl font-bold text-surface-900">分镜设计</h1>
          <p className="text-sm text-surface-500 mt-0.5">
            可视化编排分镜：添加场景框、角色标记、箭头过渡，选中对象后在右侧面板编辑属性
          </p>
        </div>
        <div className="flex items-center gap-3">
          {message && (
            <span className="text-sm text-primary-600 max-w-xs truncate">
              {message}
            </span>
          )}
          <button
            onClick={handleGenerateFromScript}
            disabled={generating}
            className="btn-primary flex items-center gap-2 disabled:opacity-60"
          >
            {generating ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Sparkles size={16} />
            )}
            {generating ? "生成中..." : "从剧本生成分镜"}
          </button>
        </div>
      </div>
      <div className="flex-1 min-h-0">
        <StoryboardCanvas />
      </div>
    </div>
  );
}
