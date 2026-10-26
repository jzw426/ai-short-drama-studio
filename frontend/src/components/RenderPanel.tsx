"use client";

import { useState } from "react";
import { Settings2, Monitor, Smartphone, Film } from "lucide-react";

interface RenderTask {
  id: string;
  name: string;
  status: string;
  progress: number;
  startTime?: string;
}

interface RenderPanelProps {
  task: RenderTask;
}

const resolutionOptions = [
  { label: "720p (HD)", value: "1280x720" },
  { label: "1080p (Full HD)", value: "1920x1080", default: true },
  { label: "2K", value: "2560x1440" },
];

const aspectRatioOptions = [
  { label: "9:16 (竖屏)", value: "9:16", device: "smartphone" },
  { label: "16:9 (横屏)", value: "16:9", device: "monitor" },
  { label: "1:1 (方形)", value: "1:1", device: "square" },
];

const styleOptions = [
  "电影级（Cinematic）",
  "纪录片风",
  "动漫风格",
  "复古胶片",
];

export function RenderPanel({ task }: RenderPanelProps) {
  const [resolution, setResolution] = useState("1920x1080");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [selectedStyle, setSelectedStyle] = useState(styleOptions[0]);
  const [fps, setFps] = useState(24);
  const [addSubtitles, setAddSubtitles] = useState(true);
  const [addBGM, setAddBGM] = useState(true);

  return (
    <div className="card p-5 space-y-5">
      <div className="flex items-center gap-2">
        <Settings2 size={18} className="text-surface-500" />
        <h3 className="font-semibold text-surface-700">渲染配置 — {task.name}</h3>
      </div>

      {/* 画幅比例 */}
      <div>
        <label className="text-sm font-medium text-surface-600 mb-2 block">
          画幅比例
        </label>
        <div className="flex gap-2">
          {aspectRatioOptions.map((opt) => {
            const Icon =
              opt.device === "smartphone"
                ? Smartphone
                : opt.device === "monitor"
                ? Monitor
                : Film;
            return (
              <button
                key={opt.value}
                onClick={() => setAspectRatio(opt.value)}
                className={`flex-1 flex items-center gap-2 px-3 py-2.5 rounded-lg border text-sm transition-all ${
                  aspectRatio === opt.value
                    ? "border-primary-500 bg-primary-50 text-primary-700"
                    : "border-surface-200 text-surface-600 hover:border-surface-300"
                }`}
              >
                <Icon size={16} />
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* 分辨率 */}
      <div>
        <label className="text-sm font-medium text-surface-600 mb-2 block">
          分辨率
        </label>
        <div className="flex gap-2">
          {resolutionOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setResolution(opt.value)}
              className={`flex-1 px-3 py-2 rounded-lg border text-sm transition-all ${
                resolution === opt.value
                  ? "border-primary-500 bg-primary-50 text-primary-700"
                  : "border-surface-200 text-surface-600 hover:border-surface-300"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* 视觉风格 & FPS 行 */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-medium text-surface-600 mb-2 block">
            视觉风格
          </label>
          <select
            value={selectedStyle}
            onChange={(e) => setSelectedStyle(e.target.value)}
            className="input-field"
          >
            {styleOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-sm font-medium text-surface-600 mb-2 block">
            帧率 (FPS)
          </label>
          <select
            value={fps}
            onChange={(e) => setFps(Number(e.target.value))}
            className="input-field"
          >
            <option value={24}>24 fps (电影标准)</option>
            <option value={30}>30 fps</option>
            <option value={60}>60 fps</option>
          </select>
        </div>
      </div>

      {/* 附加选项 */}
      <div className="flex gap-6">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={addSubtitles}
            onChange={(e) => setAddSubtitles(e.target.checked)}
            className="w-4 h-4 rounded border-surface-300 text-primary-600 focus:ring-primary-500"
          />
          <span className="text-sm text-surface-700">自动添加字幕</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={addBGM}
            onChange={(e) => setAddBGM(e.target.checked)}
            className="w-4 h-4 rounded border-surface-300 text-primary-600 focus:ring-primary-500"
          />
          <span className="text-sm text-surface-700">添加背景音乐</span>
        </label>
      </div>

      {/* 摘要 */}
      <div className="bg-surface-50 rounded-lg p-3 text-sm text-surface-500 space-y-1">
        <p>
          输出规格：{resolution} · {aspectRatio} · {fps}fps · {selectedStyle}
        </p>
        <p>
          附加：{addSubtitles ? "自动字幕" : "无字幕"} ·{" "}
          {addBGM ? "背景音乐" : "无音乐"}
        </p>
        <p className="text-xs text-surface-400 mt-1">
          预估渲染时间：约 {Math.floor(3 + Math.random() * 8)} 分钟
        </p>
      </div>

      {/* 操作按钮 */}
      <div className="flex gap-3 pt-2">
        <button className="btn-primary flex-1">确认并开始渲染</button>
        <button className="btn-secondary">重置配置</button>
      </div>
    </div>
  );
}
