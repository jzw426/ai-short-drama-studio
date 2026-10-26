"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  Upload,
  Image as ImageIcon,
  Film,
  Music,
  Trash2,
  Search,
  LayoutGrid,
  List,
  Loader2,
  AlertTriangle,
  RefreshCw,
  Play,
  Link2,
  X,
  FolderOpen,
} from "lucide-react";
import { assetApi, mediaUrl } from "@/lib/api";
import type { AssetDto } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import { useCurrentProject } from "@/lib/useCurrentProject";

type AssetType = AssetDto["type"];
type FilterType = "all" | AssetType;

interface UploadItem {
  id: string;
  name: string;
  percent: number;
  status: "uploading" | "done" | "error";
  error?: string;
}

const FILTERS: { value: FilterType; label: string; icon: typeof ImageIcon }[] = [
  { value: "all", label: "全部", icon: FolderOpen },
  { value: "image", label: "图片", icon: ImageIcon },
  { value: "video", label: "视频", icon: Film },
  { value: "audio", label: "音频", icon: Music },
];

const TYPE_META: Record<AssetType, { label: string; icon: typeof ImageIcon; cls: string }> = {
  image: { label: "图片", icon: ImageIcon, cls: "bg-blue-100 text-blue-700" },
  video: { label: "视频", icon: Film, cls: "bg-purple-100 text-purple-700" },
  audio: { label: "音频", icon: Music, cls: "bg-amber-100 text-amber-700" },
};

export default function AssetsPage() {
  const { project, loading: projectLoading, error: projectError } = useCurrentProject();

  const [assets, setAssets] = useState<AssetDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterType>("all");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [dragOver, setDragOver] = useState(false);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [preview, setPreview] = useState<AssetDto | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploading = uploads.some((u) => u.status === "uploading");

  const reload = useCallback(async (projectId: string) => {
    setLoading(true);
    try {
      const list = (await assetApi.list(projectId)) as unknown as AssetDto[];
      setAssets(Array.isArray(list) ? list : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载素材失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (project) void reload(project.id);
  }, [project, reload]);

  const visible = useMemo(() => {
    const kw = search.trim().toLowerCase();
    return assets.filter((a) => {
      if (filter !== "all" && a.type !== filter) return false;
      if (!kw) return true;
      return (
        a.name.toLowerCase().includes(kw) ||
        (a.tags || []).some((t) => t.toLowerCase().includes(kw))
      );
    });
  }, [assets, filter, search]);

  const totalSize = useMemo(
    () => visible.reduce((sum, a) => sum + (a.size || 0), 0),
    [visible]
  );

  const uploadOne = async (projectId: string, file: File, queueId: string) => {
    const form = new FormData();
    // 字段名必须是 file —— 后端 File(...) 直接取这个键，改名即 422
    form.append("file", file);
    try {
      await assetApi.upload(projectId, form, (percent) => {
        setUploads((prev) =>
          prev.map((u) => (u.id === queueId ? { ...u, percent } : u))
        );
      });
      setUploads((prev) =>
        prev.map((u) =>
          u.id === queueId ? { ...u, status: "done", percent: 100 } : u
        )
      );
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : "上传失败";
      setUploads((prev) =>
        prev.map((u) =>
          u.id === queueId ? { ...u, status: "error", error: msg } : u
        )
      );
      toast.error(`${file.name}：${msg}`);
      return false;
    }
  };

  const handleFiles = async (fileList: FileList | File[]) => {
    if (!project) return;
    const files = Array.from(fileList);
    if (!files.length) return;

    const projectId = project.id;
    const queue: UploadItem[] = files.map((f, i) => ({
      id: `${Date.now()}-${i}-${f.name}`,
      name: f.name,
      percent: 0,
      status: "uploading",
    }));
    setUploads((prev) => [...queue, ...prev]);

    let ok = 0;
    // 顺序上传：并发会让"总进度"失去意义，也更容易在后端临时目录里堆积大文件
    for (let i = 0; i < files.length; i += 1) {
      const success = await uploadOne(projectId, files[i], queue[i].id);
      if (success) ok += 1;
    }

    if (ok > 0) {
      toast.success(`已上传 ${ok} 个文件`);
      await reload(projectId);
    }
    // 成功后从队列里移除已完成项，只留错误项方便重试
    setUploads((prev) => prev.filter((u) => u.status === "error"));
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (uploading) {
      toast.error("还有文件在上传，请稍候");
      return;
    }
    void handleFiles(e.dataTransfer.files);
  };

  const handleDelete = async (asset: AssetDto) => {
    if (!window.confirm(`删除素材「${asset.name}」？此操作不可撤销。`)) return;
    try {
      await assetApi.delete(asset.id);
      toast.success("已删除");
      if (preview?.id === asset.id) setPreview(null);
      if (project) await reload(project.id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const handleCopyUrl = async (asset: AssetDto) => {
    const url = mediaUrl(asset.url);
    if (!url) {
      toast.error("素材地址为空");
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      toast.success("已复制链接（6 小时内有效，过期请刷新页面）");
    } catch {
      toast.error("复制失败，请手动复制");
    }
  };

  if (!project) {
    return (
      <div className="max-w-3xl mx-auto mt-20 card p-10 text-center space-y-4">
        <FolderOpen size={40} className="mx-auto text-surface-300" />
        <h2 className="text-lg font-semibold text-surface-800">还没有选中项目</h2>
        <p className="text-sm text-surface-500">
          {projectLoading ? "正在加载项目列表…" : projectError || "先选择一个项目，素材按项目隔离。"}
        </p>
        <Link href="/" className="btn-primary inline-flex items-center gap-2">
          去选择项目
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">素材库</h1>
          <p className="text-surface-500 mt-1">
            {project.title} · 共 {visible.length} 个素材 · {formatBytes(totalSize)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void reload(project.id)}
            disabled={loading}
            className="btn-outline flex items-center gap-2 disabled:opacity-60"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
            刷新
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="btn-primary flex items-center gap-2 disabled:opacity-60"
          >
            <Upload size={16} />
            {uploading ? "上传中…" : "上传素材"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,video/*,audio/*"
            className="hidden"
            onChange={(e) => {
              if (e.target.files) void handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* 上传队列（真实进度，后端返回前不会假造 100%） */}
      {uploads.length > 0 && (
        <div className="card p-3 space-y-2">
          {uploads.map((u) => (
            <div key={u.id} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-surface-700">{u.name}</span>
                <span
                  className={
                    u.status === "error"
                      ? "text-red-600 flex-shrink-0"
                      : "text-surface-400 flex-shrink-0"
                  }
                >
                  {u.status === "error" ? u.error : `${u.percent}%`}
                </span>
              </div>
              {u.status !== "error" && (
                <div className="mt-1 w-full h-1.5 bg-surface-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary-500 rounded-full transition-all"
                    style={{ width: `${u.percent}%` }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 拖拽区 */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!uploading) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !uploading && fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
          dragOver
            ? "border-primary-500 bg-primary-50"
            : "border-surface-200 hover:border-surface-300 bg-white"
        }`}
      >
        <Upload size={22} className="mx-auto text-surface-400" />
        <p className="mt-2 text-sm text-surface-600">
          把图片 / 视频 / 音频拖到这里，或点击选择文件
        </p>
        <p className="text-xs text-surface-400 mt-1">
          单文件上限由后端控制（默认 500MB）；上传后会立即出现在下方列表
        </p>
      </div>

      {/* 工具栏 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          {FILTERS.map((f) => {
            const Icon = f.icon;
            const active = filter === f.value;
            return (
              <button
                key={f.value}
                onClick={() => setFilter(f.value)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border transition-all ${
                  active
                    ? "border-primary-500 bg-primary-50 text-primary-700"
                    : "border-surface-200 text-surface-600 hover:border-surface-300"
                }`}
              >
                <Icon size={14} />
                {f.label}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索名称或标签"
              className="input-field pl-8 w-56"
            />
          </div>
          <div className="flex border border-surface-200 rounded-lg overflow-hidden">
            <button
              onClick={() => setView("grid")}
              className={`p-2 ${view === "grid" ? "bg-surface-100 text-surface-800" : "text-surface-400"}`}
              title="网格"
            >
              <LayoutGrid size={16} />
            </button>
            <button
              onClick={() => setView("list")}
              className={`p-2 ${view === "list" ? "bg-surface-100 text-surface-800" : "text-surface-400"}`}
              title="列表"
            >
              <List size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* 内容 */}
      {loading && assets.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-surface-400 p-6">
          <Loader2 size={16} className="animate-spin" />
          加载中…
        </div>
      ) : visible.length === 0 ? (
        <div className="card p-10 text-center space-y-2">
          <FolderOpen size={36} className="mx-auto text-surface-300" />
          <p className="text-surface-600">
            {assets.length === 0 ? "这个项目还没有素材" : "没有匹配的素材"}
          </p>
          <p className="text-xs text-surface-400">
            {assets.length === 0
              ? "上传图片、视频或音频后，可在分镜/渲染配置里引用"
              : "换个关键词或类型筛选试试"}
          </p>
        </div>
      ) : view === "grid" ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {visible.map((asset) => {
            const meta = TYPE_META[asset.type];
            const Icon = meta.icon;
            return (
              <div
                key={asset.id}
                className="card overflow-hidden group relative"
              >
                <div
                  className="aspect-video bg-surface-100 flex items-center justify-center cursor-pointer relative overflow-hidden"
                  onClick={() => setPreview(asset)}
                >
                  {asset.type === "image" ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={mediaUrl(asset.thumbnail_url || asset.url)}
                      alt={asset.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="flex flex-col items-center text-surface-400">
                      <Icon size={32} />
                      <span className="text-xs mt-1">{meta.label}</span>
                    </div>
                  )}
                  {asset.type !== "image" && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setPreview(asset);
                      }}
                      className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/30 transition-colors"
                      title="预览"
                    >
                      <Play
                        size={26}
                        className="text-white opacity-0 group-hover:opacity-100"
                      />
                    </button>
                  )}
                </div>
                <div className="p-3 space-y-1.5">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-surface-800 truncate" title={asset.name}>
                      {asset.name}
                    </p>
                    <span className={`text-xs px-1.5 py-0.5 rounded flex-shrink-0 ${meta.cls}`}>
                      {meta.label}
                    </span>
                  </div>
                  <p className="text-xs text-surface-400">
                    {formatBytes(asset.size)} · {formatDateTime(asset.uploaded_at)}
                  </p>
                  {asset.tags?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {asset.tags.slice(0, 3).map((t) => (
                        <span
                          key={t}
                          className="text-[11px] px-1.5 py-0.5 rounded bg-surface-100 text-surface-500"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-1 pt-1">
                    <button
                      onClick={() => setPreview(asset)}
                      className="text-xs px-2 py-1 rounded hover:bg-surface-100 text-surface-600"
                    >
                      预览
                    </button>
                    <button
                      onClick={() => void handleCopyUrl(asset)}
                      className="text-xs px-2 py-1 rounded hover:bg-surface-100 text-surface-600 flex items-center gap-1"
                    >
                      <Link2 size={12} />
                      链接
                    </button>
                    <button
                      onClick={() => void handleDelete(asset)}
                      className="text-xs px-2 py-1 rounded hover:bg-red-50 text-red-600 flex items-center gap-1 ml-auto"
                    >
                      <Trash2 size={12} />
                      删除
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-50 text-surface-500">
              <tr>
                <th className="text-left font-medium px-4 py-2">名称</th>
                <th className="text-left font-medium px-4 py-2 w-24">类型</th>
                <th className="text-left font-medium px-4 py-2 w-28">大小</th>
                <th className="text-left font-medium px-4 py-2 w-44">上传时间</th>
                <th className="text-right font-medium px-4 py-2 w-40">操作</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((asset) => {
                const meta = TYPE_META[asset.type];
                return (
                  <tr key={asset.id} className="border-t border-surface-100 hover:bg-surface-50">
                    <td className="px-4 py-2">
                      <button
                        onClick={() => setPreview(asset)}
                        className="text-surface-800 hover:text-primary-600 truncate max-w-[320px] block text-left"
                        title={asset.name}
                      >
                        {asset.name}
                      </button>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-1.5 py-0.5 rounded ${meta.cls}`}>
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-surface-500">{formatBytes(asset.size)}</td>
                    <td className="px-4 py-2 text-surface-500">{formatDateTime(asset.uploaded_at)}</td>
                    <td className="px-4 py-2 text-right whitespace-nowrap">
                      <button
                        onClick={() => setPreview(asset)}
                        className="text-xs px-2 py-1 rounded hover:bg-surface-100 text-surface-600"
                      >
                        预览
                      </button>
                      <button
                        onClick={() => void handleCopyUrl(asset)}
                        className="text-xs px-2 py-1 rounded hover:bg-surface-100 text-surface-600"
                      >
                        链接
                      </button>
                      <button
                        onClick={() => void handleDelete(asset)}
                        className="text-xs px-2 py-1 rounded hover:bg-red-50 text-red-600"
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 预览弹层 */}
      {preview && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6"
          onClick={() => setPreview(null)}
        >
          <div
            className="bg-white rounded-xl max-w-4xl w-full overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-100">
              <div className="min-w-0">
                <p className="font-medium text-surface-800 truncate">{preview.name}</p>
                <p className="text-xs text-surface-400">
                  {TYPE_META[preview.type].label} · {formatBytes(preview.size)} ·{" "}
                  {formatDateTime(preview.uploaded_at)}
                </p>
              </div>
              <button
                onClick={() => setPreview(null)}
                className="p-1 rounded hover:bg-surface-100 text-surface-500"
              >
                <X size={18} />
              </button>
            </div>
            <div className="bg-surface-900 flex items-center justify-center max-h-[70vh] overflow-auto">
              {preview.type === "image" ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={mediaUrl(preview.url)}
                  alt={preview.name}
                  className="max-h-[70vh] object-contain"
                />
              ) : preview.type === "video" ? (
                <video
                  controls
                  autoPlay
                  src={mediaUrl(preview.url)}
                  className="max-h-[70vh] w-full"
                />
              ) : (
                <audio controls autoPlay src={mediaUrl(preview.url)} className="w-full m-8" />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
