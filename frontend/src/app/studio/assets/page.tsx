"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload,
  Image as ImageIcon,
  Music,
  Video,
  Search,
  Filter,
  Grid3X3,
  List,
  Trash2,
  Download,
  MoreVertical,
} from "lucide-react";

interface Asset {
  id: string;
  name: string;
  type: "image" | "audio" | "video";
  mimeType: string;
  size: number;
  url: string;
  thumbnailUrl?: string;
  tags: string[];
  uploadedAt: string;
  duration?: number;
  width?: number;
  height?: number;
}

const demoAssets: Asset[] = [
  {
    id: "a1",
    name: "都市背景_咖啡馆.jpg",
    type: "image",
    mimeType: "image/jpeg",
    size: 2516582,
    url: "",
    tags: ["场景", "都市"],
    uploadedAt: "2026-06-10",
    width: 1920,
    height: 1080,
  },
  {
    id: "a2",
    name: "紧张氛围BGM.mp3",
    type: "audio",
    mimeType: "audio/mpeg",
    size: 3250585,
    url: "",
    tags: ["BGM", "紧张"],
    uploadedAt: "2026-06-09",
    duration: 180,
  },
  {
    id: "a3",
    name: "试拍镜头001.mp4",
    type: "video",
    mimeType: "video/mp4",
    size: 47453132,
    url: "",
    tags: ["试拍", "测试"],
    uploadedAt: "2026-06-08",
    duration: 45,
    width: 1920,
    height: 1080,
  },
  {
    id: "a4",
    name: "角色_李明_正面.png",
    type: "image",
    mimeType: "image/png",
    size: 1887436,
    url: "",
    tags: ["角色", "李明"],
    uploadedAt: "2026-06-07",
    width: 1024,
    height: 1024,
  },
  {
    id: "a5",
    name: "片头动画_v2.mp4",
    type: "video",
    mimeType: "video/mp4",
    size: 30100316,
    url: "",
    tags: ["片头", "动画"],
    uploadedAt: "2026-06-06",
    duration: 15,
    width: 1920,
    height: 1080,
  },
];

const typeIcons: Record<string, React.ElementType> = {
  image: ImageIcon,
  audio: Music,
  video: Video,
};

const typeColors: Record<string, string> = {
  image: "bg-blue-100 text-blue-600",
  audio: "bg-purple-100 text-purple-600",
  video: "bg-orange-100 text-orange-600",
};

const typeLabels: Record<string, string> = {
  image: "图片",
  audio: "音频",
  video: "视频",
};

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>(demoAssets);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [filterType, setFilterType] = useState<string>("all");
  const [searchTerm, setSearchTerm] = useState("");

  const onDrop = useCallback((acceptedFiles: File[]) => {
    acceptedFiles.forEach((file) => {
      const newAsset: Asset = {
        id: `a${Date.now()}`,
        name: file.name,
        type: file.type.startsWith("image")
          ? "image"
          : file.type.startsWith("audio")
          ? "audio"
          : "video",
        mimeType: file.type,
        size: file.size,
        url: "",
        tags: [],
        uploadedAt: new Date().toISOString().split("T")[0],
      };
      setAssets((prev) => [newAsset, ...prev]);
    });
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "image/*": [".png", ".jpg", ".jpeg", ".webp", ".gif"],
      "audio/*": [".mp3", ".wav", ".ogg"],
      "video/*": [".mp4", ".webm", ".mov"],
    },
  });

  const filteredAssets = assets.filter((a) => {
    const matchType = filterType === "all" || a.type === filterType;
    const matchSearch = a.name.toLowerCase().includes(searchTerm.toLowerCase());
    return matchType && matchSearch;
  });

  return (
    <div className="max-w-7xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">素材库</h1>
          <p className="text-surface-500 mt-1">
            管理图片、音频、视频素材，共 {assets.length} 个文件
          </p>
        </div>
      </div>

      {/* 上传区域 */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
          isDragActive
            ? "border-primary-500 bg-primary-50"
            : "border-surface-300 hover:border-primary-400 hover:bg-surface-50"
        }`}
      >
        <input {...getInputProps()} />
        <Upload size={40} className="mx-auto text-surface-400 mb-3" />
        <p className="text-surface-600 font-medium">
          {isDragActive ? "松开以上传文件" : "拖拽文件到此处上传"}
        </p>
        <p className="text-surface-400 text-sm mt-1">
          支持 JPG、PNG、MP3、WAV、MP4 等格式
        </p>
      </div>

      {/* 工具栏 */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search
            size={18}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400"
          />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="搜索素材名称..."
            className="input-field pl-10"
          />
        </div>

        <div className="flex items-center gap-2">
          {["all", "image", "audio", "video"].map((t) => (
            <button
              key={t}
              onClick={() => setFilterType(t)}
              className={`px-3 py-1.5 rounded-lg text-sm transition-all ${
                filterType === t
                  ? "bg-primary-100 text-primary-700 font-medium"
                  : "bg-surface-100 text-surface-600 hover:bg-surface-200"
              }`}
            >
              {t === "all" ? "全部" : typeLabels[t]}
            </button>
          ))}
        </div>

        <div className="flex items-center border border-surface-300 rounded-lg overflow-hidden">
          <button
            onClick={() => setViewMode("grid")}
            className={`p-2 ${viewMode === "grid" ? "bg-primary-50 text-primary-600" : "text-surface-400 hover:text-surface-600"}`}
          >
            <Grid3X3 size={18} />
          </button>
          <button
            onClick={() => setViewMode("list")}
            className={`p-2 ${viewMode === "list" ? "bg-primary-50 text-primary-600" : "text-surface-400 hover:text-surface-600"}`}
          >
            <List size={18} />
          </button>
        </div>
      </div>

      {/* 素材展示 */}
      {viewMode === "grid" ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {filteredAssets.map((asset) => {
            const Icon = typeIcons[asset.type];
            const sizeStr = asset.size > 1024 * 1024
              ? `${(asset.size / 1024 / 1024).toFixed(1)} MB`
              : asset.size > 1024
              ? `${(asset.size / 1024).toFixed(1)} KB`
              : `${asset.size} B`;
            return (
              <div key={asset.id} className="card group">
                <div className="aspect-square bg-surface-100 rounded-t-xl flex items-center justify-center relative">
                  <div className={`p-3 rounded-full ${typeColors[asset.type]}`}>
                    <Icon size={28} />
                  </div>
                  <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button className="p-1.5 bg-white rounded-md shadow-sm hover:bg-red-50 text-surface-400 hover:text-red-500">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
                <div className="p-3">
                  <p className="text-sm font-medium text-surface-800 truncate">
                    {asset.name}
                  </p>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-xs text-surface-400">
                      {sizeStr}
                    </span>
                    <span className="text-xs text-surface-400">
                      {asset.uploadedAt}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="card">
          <table className="w-full">
            <thead>
              <tr className="border-b border-surface-200">
                <th className="text-left p-3 text-xs text-surface-400 font-medium">
                  文件名
                </th>
                <th className="text-left p-3 text-xs text-surface-400 font-medium">
                  类型
                </th>
                <th className="text-left p-3 text-xs text-surface-400 font-medium">
                  大小
                </th>
                <th className="text-left p-3 text-xs text-surface-400 font-medium">
                  上传时间
                </th>
                <th className="p-3 w-10" />
              </tr>
            </thead>
            <tbody>
              {filteredAssets.map((asset) => {
                const Icon = typeIcons[asset.type];
                const sizeStr = asset.size > 1024 * 1024
                  ? `${(asset.size / 1024 / 1024).toFixed(1)} MB`
                  : asset.size > 1024
                  ? `${(asset.size / 1024).toFixed(1)} KB`
                  : `${asset.size} B`;
                return (
                  <tr
                    key={asset.id}
                    className="border-b border-surface-100 hover:bg-surface-50"
                  >
                    <td className="p-3 flex items-center gap-2">
                      <Icon size={18} className="text-surface-400" />
                      <span className="text-sm text-surface-800">
                        {asset.name}
                      </span>
                    </td>
                    <td className="p-3">
                      <span
                        className={`text-xs px-2 py-0.5 rounded ${typeColors[asset.type]}`}
                      >
                        {typeLabels[asset.type]}
                      </span>
                    </td>
                    <td className="p-3 text-sm text-surface-500">
                      {sizeStr}
                    </td>
                    <td className="p-3 text-sm text-surface-400">
                      {asset.uploadedAt}
                    </td>
                    <td className="p-3">
                      <button className="p-1 hover:bg-surface-200 rounded text-surface-400">
                        <MoreVertical size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
