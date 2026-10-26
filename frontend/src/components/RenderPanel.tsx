"use client";

import { useState } from "react";
import { Settings2, Monitor, Smartphone, Film, Loader2, Play } from "lucide-react";
import type { RenderConfigPayload } from "@/lib/api";

type SubtitleSource = "dialogue" | "description" | "label" | "none";

interface RenderPanelProps {
  onSubmit: (config: RenderConfigPayload) => void | Promise<void>;
  submitting: boolean;
  disabled?: boolean;
  shotCount?: number | null;
}

const resolutionOptions = [
  { label: "720p (HD)", value: "1280x720" },
  { label: "1080p (Full HD)", value: "1920x1080" },
  { label: "2K", value: "2560x1440" },
];

const aspectRatioOptions = [
  { label: "9:16 (竖屏)", value: "9:16", device: "smartphone" },
  { label: "16:9 (横屏)", value: "16:9", device: "monitor" },
  { label: "1:1 (方形)", value: "1:1", device: "square" },
];

const styleOptions = ["电影级（Cinematic）", "纪录片风", "动漫风格", "复古胶片"];

const subtitleSourceOptions = [
  { value: "dialogue", label: "剧本台词（推荐）" },
  { value: "description", label: "镜头画面描述" },
  { value: "label", label: "镜头标签" },
  { value: "none", label: "不烧字幕" },
] as const;

const DEFAULTS = {
  resolution: "1920x1080",
  aspectRatio: "9:16",
  style: styleOptions[0],
  fps: 24,
  addSubtitles: true,
  subtitleSource: "dialogue" as SubtitleSource,
  addBGM: true,
};

export function RenderPanel({
  onSubmit,
  submitting,
  disabled,
  shotCount,
}: RenderPanelProps) {
  const [resolution, setResolution] = useState(DEFAULTS.resolution);
  const [aspectRatio, setAspectRatio] = useState(DEFAULTS.aspectRatio);
  const [selectedStyle, setSelectedStyle] = useState(DEFAULTS.style);
  const [fps, setFps] = useState(DEFAULTS.fps);
  const [addSubtitles, setAddSubtitles] = useState(DEFAULTS.addSubtitles);
  const [subtitleSource, setSubtitleSource] =
    useState<SubtitleSource>(DEFAULTS.subtitleSource);
  const [addBGM, setAddBGM] = useState(DEFAULTS.addBGM);

  const reset = () => {
    setResolution(DEFAULTS.resolution);
    setAspectRatio(DEFAULTS.aspectRatio);
    setSelectedStyle(DEFAULTS.style);
    setFps(DEFAULTS.fps);
    setAddSubtitles(DEFAULTS.addSubtitles);
    setSubtitleSource(DEFAULTS.subtitleSource);
    setAddBGM(DEFAULTS.addBGM);
  };

  const handleSubmit = () => {
    void onSubmit({
      resolution,
      aspect_ratio: aspectRatio,
      fps,
      visual_style: selectedStyle,
      add_subtitles: addSubtitles && subtitleSource !== "none",
      subtitle_source: addSubtitles ? subtitleSource : "none",
      add_bgm: addBGM,
      bgm_source: null,
      quality: "high",
      ai_model: "kling",
    });
  };

  const canSubmit = !submitting && !disabled;

  return (
    <div className="card p-5 space-y-5">
      <div className="flex items-center gap-2">
        <Settings2 size={18} className="text-surface-500" />
        <h3 className="font-semibold text-surface-700">渲染配置</h3>
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
                type="button"
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
              type="button"
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
      <div className="space-y-3">
        <div className="flex items-center gap-6 flex-wrap">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={addSubtitles}
              onChange={(e) => setAddSubtitles(e.target.checked)}
              className="w-4 h-4 rounded border-surface-300 text-primary-600 focus:ring-primary-500"
            />
            <span className="text-sm text-surface-700">烧录字幕</span>
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

        {addSubtitles && (
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm text-surface-600">字幕来源</span>
            <select
              value={subtitleSource}
              onChange={(e) =>
                setSubtitleSource(e.target.value as SubtitleSource)
              }
              className="input-field max-w-[220px]"
            >
              {subtitleSourceOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <span className="text-xs text-surface-400">
              {subtitleSource === "dialogue"
                ? "按镜头的场景引用取剧本台词；没有台词的镜头回退画面描述"
                : "取镜头字段；台词请选「剧本台词」"}
            </span>
          </div>
        )}
      </div>

      {/* 摘要 */}
      <div className="bg-surface-50 rounded-lg p-3 text-sm text-surface-500 space-y-1">
        <p>
          输出规格：{resolution} · {aspectRatio} · {fps}fps · {selectedStyle}
        </p>
        <p>
          附加：{addSubtitles ? "字幕" : "无字幕"} ·{" "}
          {addBGM ? "背景音乐" : "无音乐"}
        </p>
        <p className="text-xs text-surface-400 mt-1">
          {shotCount && shotCount > 0
            ? `将渲染 ${shotCount} 个镜头，每镜一次 AI 视频生成；耗时取决于模型响应，通常 3–15 分钟`
            : "尚无镜头：请先在分镜设计里生成或添加镜头，否则没有可渲染的内容"}
        </p>
      </div>

      {/* 操作按钮 */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="btn-primary flex-1 flex items-center justify-center gap-2 disabled:opacity-60"
        >
          {submitting ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              正在提交…
            </>
          ) : (
            <>
              <Play size={16} />
              确认并开始渲染
            </>
          )}
        </button>
        <button
          type="button"
          onClick={reset}
          disabled={submitting}
          className="btn-secondary disabled:opacity-60"
        >
          重置配置
        </button>
      </div>
    </div>
  );
}
