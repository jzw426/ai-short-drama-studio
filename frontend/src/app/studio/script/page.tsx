"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, Download, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { scriptApi } from "@/lib/api";
import { useCurrentProject } from "@/lib/useCurrentProject";
import { ScriptEditor } from "@/components/ScriptEditor";

export default function ScriptPage() {
  const { project, loading: projectLoading, error: projectError } = useCurrentProject();
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    if (!project || exporting) return;
    setExporting(true);
    try {
      // 导出走后端 /script/export（包含场景、地点、台词等结构化内容）
      const text = await scriptApi.exportText(project.id, "markdown");
      const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${project.title}-剧本.md`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.success("剧本已导出");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出剧本失败");
    } finally {
      setExporting(false);
    }
  };

  if (!project) {
    return (
      <div className="max-w-3xl mx-auto mt-20 card p-10 text-center space-y-4">
        <FileText size={36} className="mx-auto text-surface-300" />
        <p className="text-surface-500">
          {projectLoading
            ? "正在加载项目列表…"
            : projectError ?? "先在首页新建或选择一个项目，再回来写剧本。"}
        </p>
        <Link href="/" className="btn-primary inline-flex">
          去选择项目
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-5 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">剧本工坊</h1>
          <p className="text-sm text-surface-500 mt-1">
            当前项目：{project.title}
          </p>
        </div>
        <button
          onClick={() => void handleExport()}
          disabled={exporting}
          className="btn-outline flex items-center gap-2 text-sm disabled:opacity-60"
        >
          {exporting ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Download size={16} />
          )}
          {exporting ? "导出中…" : "导出 Markdown"}
        </button>
      </div>

      <ScriptEditor key={project.id} projectId={project.id} />
    </div>
  );
}
