"use client";

import { useState } from "react";
import { ScriptEditor } from "@/components/ScriptEditor";
import { Download, Loader2 } from "lucide-react";
import { scriptApi } from "@/lib/api";
import { useProjectStore } from "@/store/useProjectStore";

export default function ScriptPage() {
  const currentProject = useProjectStore((s) => s.currentProject);
  const [exporting, setExporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleExport = async (format: "markdown" | "txt") => {
    if (!currentProject) {
      setMessage("请先在首页新建或选择一个项目");
      return;
    }
    setExporting(true);
    setMessage(null);
    try {
      const text = await scriptApi.exportText(currentProject.id, format);
      const blob = new Blob([text], {
        type: "text/plain;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `script_${currentProject.id.slice(0, 8)}.${format === "markdown" ? "md" : "txt"}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setMessage("剧本已导出");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="h-full flex flex-col animate-fade-in">
      <div className="flex items-center justify-between px-6 py-4 border-b border-surface-200 bg-white flex-shrink-0">
        <div>
          <h1 className="text-xl font-bold text-surface-900">剧本工坊</h1>
          <p className="text-sm text-surface-500 mt-0.5">
            基于场景管理的专业剧本编辑器，支持 AI 辅助生成
          </p>
        </div>
        <div className="flex items-center gap-3">
          {message && (
            <span className="text-sm text-primary-600">{message}</span>
          )}
          <button
            onClick={() => handleExport("markdown")}
            disabled={exporting}
            className="btn-outline flex items-center gap-2 disabled:opacity-60"
          >
            {exporting ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Download size={16} />
            )}
            导出 Markdown
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 p-4">
        <ScriptEditor />
      </div>
    </div>
  );
}
