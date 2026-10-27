"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Film,
  Image as ImageIcon,
  Loader2,
  Play,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  mediaUrl,
  storyboardApi,
  videoJobApi,
  type FirstFrameDto,
  type ShotDto,
  type VideoJobDto,
  type VideoJobStatus,
} from "@/lib/api";
import {
  firstFrameErrorMessage,
  isVideoJobInflight,
  isVideoJobTerminal,
  videoJobErrorMessage,
  videoJobStatusText,
} from "@/lib/aiErrors";

/**
 * 轮询间隔：视频供应商的作业本来就以分钟计，5s 足够，也不会把后端打爆
 * （后端自己还有 next_poll_at 节流，前端只是低频问结果）。
 */
const POLL_INTERVAL_MS = 5000;

/**
 * 轮询上限 30 分钟（30*60/5 = 360 次）。
 *
 * 为什么前端也要有上限：后端作业理论上会自己转 timeout，但后端重启/作业行
 * 丢失时状态会永远停在 polling。没有前端上限，页面就会一直每 5s 发请求到刷新为止。
 */
const MAX_POLLS = Math.floor((30 * 60 * 1000) / POLL_INTERVAL_MS);

/**
 * 时长兜底：后端 VideoJobCreate 卡的是 3~18 秒（provider 只接受 8n+1 帧），
 * 但老分镜的 duration 可能是 2 秒或干脆是脏数据——超范围会在提交时 422，
 * 用户看到的是"莫名其妙的参数错误"，所以这里先夹到合法区间，缺失用 5 秒。
 */
function clampVideoDuration(duration: number | null | undefined): number {
  const raw = Number(duration);
  if (!Number.isFinite(raw) || raw <= 0) return 5;
  return Math.min(18, Math.max(3, raw));
}

interface JobState {
  jobId: string;
  status: VideoJobStatus;
  /** 前端本地轮询次数，用于「生成中 12/360」 */
  polls: number;
  videoUrl?: string | null;
  errorText?: string | null;
}

interface Props {
  projectId: string;
  shot: ShotDto;
  /** 首帧图/视频产物落库后刷新分镜列表（父级负责，避免这里重复维护镜头数据） */
  onShotsChanged?: () => void | Promise<void>;
}

/**
 * 镜头媒体面板（M4-3）：首帧缩略图 + 出首帧 + 出视频 + 作业轮询。
 *
 * 三层状态语义（刻意分开，别混成一个 "loading"）：
 *   1. 出首帧是同步接口（600s 超时），只有"正在出图"；
 *   2. 出视频是异步作业，submit 立即返回 job_id，之后靠轮询；
 *   3. 轮询结果可能是 completed / failed / timeout / cancelled，终态才停。
 *
 * 定时器只存在于本组件的 effect 里：组件卸载（切项目、删镜头、列表重排换 key）
 * 或 job 进入终态时 cleanup 一定会 clearTimeout，不会出现"页面走了还在打接口"。
 */
export function ShotMediaPanel({ projectId, shot, onShotsChanged }: Props) {
  const [job, setJob] = useState<JobState | null>(null);
  const [firstFrameBusy, setFirstFrameBusy] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);

  // 卸载后禁止再 setState / toast：轮询的 await 可能刚好在卸载瞬间返回
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  // 组件实例被复用（同 key 跨项目）时清掉上一个镜头的作业，避免串台
  const scopeRef = useRef(`${projectId}:${shot.id}`);
  useEffect(() => {
    const scope = `${projectId}:${shot.id}`;
    if (scopeRef.current !== scope) {
      scopeRef.current = scope;
      setJob(null);
    }
  }, [projectId, shot.id]);

  /** 查一次作业；进行中则把 polls+1 写回状态，由下面的 effect 挂下一次定时器 */
  const tick = useCallback(
    async (current: JobState) => {
      try {
        const raw = (await videoJobApi.get(
          projectId,
          current.jobId
        )) as unknown as VideoJobDto;
        if (!aliveRef.current) return;

        if (isVideoJobTerminal(raw.status)) {
          if (raw.status === "completed") {
            const videoUrl = raw.video_url ?? null;
            setJob({
              jobId: raw.id,
              status: "completed",
              polls: current.polls,
              videoUrl,
            });
            toast.success(`镜头 ${shot.shot_number} 视频已生成`);
            await onShotsChanged?.();
          } else if (raw.status === "cancelled") {
            setJob({
              jobId: raw.id,
              status: "cancelled",
              polls: current.polls,
            });
            toast("已取消视频生成");
          } else {
            // failed / timeout：后端 error 里有供应商摘要，映射后再展示
            const text = videoJobStatusText(raw.status, raw.error);
            setJob({
              jobId: raw.id,
              status: raw.status,
              polls: current.polls,
              errorText: text,
            });
            toast.error(text);
          }
          return;
        }

        const polls = current.polls + 1;
        if (polls >= MAX_POLLS) {
          setJob({
            ...current,
            status: "timeout",
            polls,
            errorText: "超时，可重试",
          });
          toast.error("视频生成超时，可重试");
          return;
        }
        setJob({ ...current, status: raw.status, polls });
      } catch {
        // 单次查询失败 ≠ 作业失败（后端重启、网络抖动都会失败一次），
        // 继续轮询到上限；不打 toast，否则 5s 一条把用户淹没。
        if (!aliveRef.current) return;
        const polls = current.polls + 1;
        if (polls >= MAX_POLLS) {
          setJob({
            ...current,
            status: "timeout",
            polls,
            errorText: "超时，可重试",
          });
          toast.error("视频生成超时，可重试");
          return;
        }
        setJob({ ...current, polls });
      }
    },
    [projectId, onShotsChanged, shot.shot_number]
  );

  // 轮询主循环：状态每变一次重挂一个 5s 定时器。
  // 终态（completed/failed/timeout/cancelled）直接不挂，定时器随之清空。
  useEffect(() => {
    if (!job || isVideoJobTerminal(job.status)) return;
    const timer = window.setTimeout(() => {
      void tick(job);
    }, POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [job, tick]);

  const handleFirstFrame = useCallback(async () => {
    if (firstFrameBusy) return;
    const regenerate = Boolean(shot.image_url);
    setFirstFrameBusy(true);
    // 出图要串行注入多张参考图，可能几十秒；给一个不会自动消失的 loading
    const loadingId = toast.loading(
      regenerate ? "正在重生首帧图…" : "正在生成首帧图…"
    );
    try {
      const res = (await storyboardApi.generateFirstFrame(projectId, shot.id, {
        regenerate,
      })) as unknown as FirstFrameDto;
      toast.success(
        res?.characters_used?.length
          ? `首帧已生成（注入角色：${res.characters_used.join("、")}）`
          : "首帧已生成",
        { id: loadingId }
      );
      await onShotsChanged?.();
    } catch (e) {
      toast.error(firstFrameErrorMessage(e), { id: loadingId });
    } finally {
      if (aliveRef.current) setFirstFrameBusy(false);
    }
  }, [firstFrameBusy, onShotsChanged, projectId, shot.id, shot.image_url]);

  const handleCreateJob = useCallback(async () => {
    if (createBusy || (job && isVideoJobInflight(job.status))) return;
    setCreateBusy(true);
    try {
      const raw = (await videoJobApi.create(projectId, shot.id, {
        // 优先用专门的视频提示词；没有就退回画面描述（老数据没有 video_prompt）
        prompt:
          shot.video_prompt?.trim() || shot.description?.trim() || undefined,
        duration: clampVideoDuration(shot.duration),
        // 有首帧才是图生视频；没有首帧时后端会退化成文生视频
        image_url: shot.image_url || undefined,
      })) as unknown as VideoJobDto;
      if (!aliveRef.current) return;
      // 入队失败时后端直接把作业标成 failed 返回（HTTP 仍是 2xx），
      // 这里必须当成失败处理，否则按钮会显示"已提交"、状态永远不动。
      if (raw.status === "failed") {
        const text = videoJobStatusText("failed", raw.error);
        setJob({ jobId: raw.id, status: "failed", polls: 0, errorText: text });
        toast.error(text);
        return;
      }
      setJob({ jobId: raw.id, status: raw.status ?? "pending", polls: 0 });
      toast.success("已提交视频生成，正在排队…");
    } catch (e) {
      toast.error(videoJobErrorMessage(e));
    } finally {
      if (aliveRef.current) setCreateBusy(false);
    }
  }, [
    createBusy,
    job,
    projectId,
    shot.id,
    shot.video_prompt,
    shot.description,
    shot.duration,
    shot.image_url,
  ]);

  const handleCancel = useCallback(async () => {
    if (!job || !isVideoJobInflight(job.status) || cancelBusy) return;
    setCancelBusy(true);
    try {
      await videoJobApi.cancel(projectId, job.jobId);
      if (!aliveRef.current) return;
      // 本地立即转 canceled，停掉轮询；后端会自己收尾（取消一个已出片的作业
      // 不会造成扣费异常，供应商侧按提交计费）。
      setJob({ ...job, status: "cancelled", errorText: null });
      toast("已取消视频生成");
    } catch (e) {
      toast.error(videoJobErrorMessage(e));
    } finally {
      if (aliveRef.current) setCancelBusy(false);
    }
  }, [job, cancelBusy, projectId]);

  const inflight = job ? isVideoJobInflight(job.status) : false;
  const hasVideo = Boolean(shot.video_url) || job?.status === "completed";
  const videoUrl = mediaUrl(job?.videoUrl ?? shot.video_url ?? null);
  const frameUrl = mediaUrl(shot.image_url);
  const polls = job?.polls ?? 0;

  let statusLine: React.ReactNode;
  if (inflight) {
    statusLine = (
      <span className="text-primary-600">
        生成中 {polls}/{MAX_POLLS} · 每 5 秒查询一次，最长 30 分钟
      </span>
    );
  } else if (job?.status === "completed") {
    statusLine = <span className="text-green-600">已生成视频</span>;
  } else if (job?.status === "cancelled") {
    statusLine = <span className="text-surface-500">已取消，可重试</span>;
  } else if (job && job.errorText) {
    statusLine = <span className="text-red-600">{job.errorText}</span>;
  } else if (hasVideo) {
    statusLine = <span className="text-green-600">已生成视频</span>;
  } else if (!frameUrl) {
    statusLine = (
      <span className="text-surface-400">
        先出首帧再出视频更稳（无首帧会退化为文生视频）
      </span>
    );
  } else {
    statusLine = <span className="text-surface-400">首帧已就绪，可出视频</span>;
  }

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex items-start gap-2">
        {/* 首帧缩略图：有 image_url 才渲染，点击看原图 */}
        <div className="relative flex h-14 w-24 flex-shrink-0 items-center justify-center overflow-hidden rounded-md border border-surface-200 bg-surface-100">
          {frameUrl ? (
            <a
              href={frameUrl}
              target="_blank"
              rel="noreferrer"
              title="查看首帧原图"
              className="block h-full w-full"
            >
              <img
                src={frameUrl}
                alt={`镜头 ${shot.shot_number} 首帧`}
                className="h-full w-full object-cover"
                loading="lazy"
              />
            </a>
          ) : (
            <span className="flex flex-col items-center gap-0.5 text-[10px] text-surface-400">
              <ImageIcon size={13} />
              无首帧
            </span>
          )}
        </div>

        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => void handleFirstFrame()}
              disabled={firstFrameBusy}
              title={
                frameUrl
                  ? "重新生成首帧（regenerate=true）"
                  : "生成首帧（注入角色锁脸图与场景四视图）"
              }
              className="btn-outline flex items-center gap-1 px-2 py-1 text-[11px] disabled:opacity-60"
            >
              {firstFrameBusy ? (
                <Loader2 size={11} className="animate-spin" />
              ) : frameUrl ? (
                <RefreshCw size={11} />
              ) : (
                <Sparkles size={11} />
              )}
              {firstFrameBusy ? "出图中…" : frameUrl ? "重生图" : "出首帧"}
            </button>

            <button
              type="button"
              onClick={() => void handleCreateJob()}
              disabled={createBusy || inflight}
              title={
                frameUrl
                  ? "用当前首帧图生视频"
                  : "无首帧时退化为文生视频（画面稳定性较差）"
              }
              className="btn-primary flex items-center gap-1 px-2 py-1 text-[11px] disabled:opacity-60"
            >
              {inflight ? (
                <Loader2 size={11} className="animate-spin" />
              ) : createBusy ? (
                <Loader2 size={11} className="animate-spin" />
              ) : hasVideo ? (
                <RefreshCw size={11} />
              ) : (
                <Film size={11} />
              )}
              {inflight
                ? `生成中 ${polls}/${MAX_POLLS}`
                : createBusy
                ? "提交中…"
                : hasVideo
                ? "重新出视频"
                : "出视频"}
            </button>

            {videoUrl && (
              <a
                href={videoUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-surface-200 px-2 py-1 text-[11px] text-surface-600 hover:text-surface-900"
              >
                <Play size={11} />
                查看视频
              </a>
            )}

            {inflight && (
              <button
                type="button"
                onClick={() => void handleCancel()}
                disabled={cancelBusy}
                className="inline-flex items-center gap-1 rounded-md border border-surface-200 px-2 py-1 text-[11px] text-surface-500 hover:text-red-600 disabled:opacity-50"
              >
                {cancelBusy ? (
                  <Loader2 size={11} className="animate-spin" />
                ) : (
                  <X size={11} />
                )}
                取消
              </button>
            )}
          </div>

          <p className="truncate text-[11px]">{statusLine}</p>
        </div>
      </div>
    </div>
  );
}
