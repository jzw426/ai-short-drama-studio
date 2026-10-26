"use client";

import React, { useRef, useEffect, useState, useCallback } from "react";

// fabric@5 通过 npm 包导入（自带 TS 类型；替代原先从未加载的全局 Script 方案）


import {
  Type,
  Square,
  Circle,
  ArrowRight,
  ImagePlus,
  Trash2,
  Undo2,
  Redo2,
  Save,
  Download,
  ChevronUp,
  ChevronDown,
  MoveUp,
  MoveDown,
} from "lucide-react";
import {
  useProjectStore,
  selectCanUndo,
  selectCanRedo,
} from "@/store/useProjectStore";
import { storyboardApi } from "@/lib/api";
import type { StoryboardObjectInfo } from "@/store/useProjectStore";

// fabric@5 仅在客户端动态加载（避免服务端构建期 require node-canvas/jsdom 失败）
let _fabricPromise: Promise<any> | null = null;
function getFabric(): Promise<any> {
  if (!_fabricPromise) {
    // fabric@5 dist 为 AMD/UMD 构建，webpack 动态 import 后命名空间形如
    // { fabric: <本体>, default: { fabric: <本体> } }，统一解包出本体
    _fabricPromise = import("fabric").then((m: any) => {
      const direct = m && m.fabric;
      const nested = m && m.default && m.default.fabric;
      const dflt = m && m.default;
      return direct || nested || dflt || m;
    });
  }
  return _fabricPromise;
}

// ===== 常量 =====

const CANVAS_WIDTH = 1280;
const CANVAS_HEIGHT = 720;
const GRID_SIZE = 40;
const SCENE_BOX_RATIO = 16 / 9;
const SCENE_BOX_WIDTH = 400;
const SCENE_BOX_HEIGHT = SCENE_BOX_WIDTH / SCENE_BOX_RATIO;

let objectIdCounter = 0;
function generateObjectId(): string {
  objectIdCounter += 1;
  return `sb_obj_${Date.now().toString(36)}_${objectIdCounter.toString(36)}`;
}

// ===== 辅助函数 =====

function drawGrid(canvas: any, fabric: any) {
  const gridColor = "#e9ecef";
  for (let i = 0; i <= CANVAS_WIDTH; i += GRID_SIZE) {
    canvas.add(
      new fabric.Line([i, 0, i, CANVAS_HEIGHT], {
        stroke: gridColor,
        selectable: false,
        evented: false,
        excludeFromExport: true,
        strokeWidth: 0.5,
      })
    );
  }
  for (let j = 0; j <= CANVAS_HEIGHT; j += GRID_SIZE) {
    canvas.add(
      new fabric.Line([0, j, CANVAS_WIDTH, j], {
        stroke: gridColor,
        selectable: false,
        evented: false,
        excludeFromExport: true,
        strokeWidth: 0.5,
      })
    );
  }
}

function buildSceneBox(sceneNumber: number, totalScenes: number, fabric: any): any {
  const rect = new fabric.Rect({
    width: SCENE_BOX_WIDTH,
    height: SCENE_BOX_HEIGHT,
    fill: "transparent",
    stroke: "#5c7cfa",
    strokeWidth: 2,
    rx: 4,
    ry: 4,
    selectable: false,
    evented: false,
  });

  const label = new fabric.Text(`场景 ${sceneNumber}`, {
    left: 8,
    top: 8,
    fontSize: 14,
    fontWeight: "bold",
    fill: "#5c7cfa",
    fontFamily: "Inter, sans-serif",
    selectable: false,
    evented: false,
  });

  const hintText =
    totalScenes > 0
      ? `共 ${totalScenes} 个场景 · 可拖入角色`
      : "暂无剧本场景";

  const hint = new fabric.Text(hintText, {
    left: SCENE_BOX_WIDTH / 2,
    top: SCENE_BOX_HEIGHT / 2,
    fontSize: 12,
    fill: "#adb5bd",
    fontFamily: "Inter, sans-serif",
    textAlign: "center",
    originX: "center",
    originY: "center",
    selectable: false,
    evented: false,
  });

  const group = new fabric.Group([rect, label, hint], {
    left: 80 + sceneNumber * 30,
    top: 80 + sceneNumber * 30,
  } as any);
  (group as any).objectType = "sceneBox";
  (group as any).sceneNumber = sceneNumber;

  return group;
}

function extractObjectInfo(obj: any): StoryboardObjectInfo {
  return {
    id: (obj as any).customId || "",
    type: (obj as any).objectType || "unknown",
    left: obj.left ?? 0,
    top: obj.top ?? 0,
    width: (obj.width ?? 0) * (obj.scaleX ?? 1),
    height: (obj.height ?? 0) * (obj.scaleY ?? 1),
    scaleX: obj.scaleX ?? 1,
    scaleY: obj.scaleY ?? 1,
    angle: obj.angle ?? 0,
    opacity: (obj.opacity ?? 1) * 100,
  };
}

// ===== 主组件 =====

export function StoryboardCanvas({ sceneCount = 0 }: { sceneCount?: number }) {
  const canvasElRef = useRef<HTMLCanvasElement>(null);
  const fabricRef = useRef<any>(null);
  const fabricLibRef = useRef<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [fabricReady, setFabricReady] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [selectedInfo, setSelectedInfo] = useState<StoryboardObjectInfo | null>(null);
  const canUndo = useProjectStore(selectCanUndo);
  const canRedo = useProjectStore(selectCanRedo);

  const {
    currentProject,
    storyboardCanvasState,
    pushStoryboardUndo,
    undoStoryboard,
    redoStoryboard,
    setStoryboardSelectedObject,
    setStoryboardCanvasState,
  } = useProjectStore();

  const spaceDownRef = useRef(false);
  const isPanningRef = useRef(false);
  const lastPanPointRef = useRef<{ x: number; y: number } | null>(null);

  // ===== 保存状态到撤销栈 =====
  const saveStateToUndoStack = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    try {
      const json = JSON.stringify(
        canvas.toJSON(["objectType", "customId", "sceneNumber", "excludeFromExport"])
      );
      // 撤销栈去重：与栈顶相同则跳过（避免空状态重复压栈）
      const stack = useProjectStore.getState().storyboardUndoStack;
      if (stack[stack.length - 1] !== json) {
        pushStoryboardUndo(json);
      }
    } catch {
      // silent
    }
  }, [pushStoryboardUndo]);

  // ===== 同步画布状态（供自动保存） =====
  const syncCanvasState = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    try {
      setStoryboardCanvasState(
        JSON.stringify(
          canvas.toJSON(["objectType", "customId", "sceneNumber", "excludeFromExport"])
        )
      );
    } catch {
      // silent
    }
  }, [setStoryboardCanvasState]);

  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "saved" | "failed"
  >("idle");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ===== 从后端加载画布状态（进入页面时恢复） =====
  useEffect(() => {
    if (!currentProject) return;
    let cancelled = false;
    storyboardApi
      .get(currentProject.id)
      .then((sb: any) => {
        if (cancelled) return;
        const raw = sb?.canvas_state;
        if (raw && raw !== "{}") {
          try {
            const parsed = JSON.parse(raw);
            if (parsed && parsed.objects && parsed.objects.length > 0) {
              setStoryboardCanvasState(raw);
            }
          } catch {
            // 损坏状态不恢复
          }
        }
      })
      .catch(() => {
        // 加载失败从零开始
      });
    return () => {
      cancelled = true;
    };
  }, [currentProject, setStoryboardCanvasState]);

  // ===== 自动保存（防抖 800ms） =====
  useEffect(() => {
    if (!currentProject || !storyboardCanvasState) return;
    setSaveStatus("saving");
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      storyboardApi
        .update(currentProject.id, { canvas_state: storyboardCanvasState })
        .then(() => setSaveStatus("saved"))
        .catch(() => {
          setSaveStatus("failed");
          console.error("[storyboard] 自动保存失败");
        });
    }, 800);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [storyboardCanvasState, currentProject]);

  // ===== 更新选中对象信息 =====
  const updateSelectionInfo = useCallback(
    (obj: any | null) => {
      if (!obj) {
        setSelectedInfo(null);
        setStoryboardSelectedObject(null);
        return;
      }
      const info = extractObjectInfo(obj);
      setSelectedInfo(info);
      setStoryboardSelectedObject(info);
    },
    [setStoryboardSelectedObject]
  );

  // ===== 图层列表 =====

  const [layers, setLayers] = useState<
    { id: string; type: string; label: string }[]
  >([]);

  const layerLabel = useCallback((obj: any): string => {
    const type = (obj as any).objectType || obj.type;
    switch (type) {
      case "sceneBox":
        return `场景框 ${(obj as any).sceneNumber ?? ""}`;
      case "i-text":
      case "text":
        return "文字";
      case "circle":
        return "圆形";
      case "arrow":
        return "箭头";
      case "image":
        return "图片";
      default:
        return String(type || "对象");
    }
  }, []);

  const refreshLayers = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    const objs = canvas
      .getObjects()
      .filter((o: any) => (o as any).objectType !== "sceneBox" || (o as any).sceneNumber !== undefined);
    setLayers(
      objs.map((o: any) => ({
        id: (o as any).customId || o.id,
        type: (o as any).objectType || o.type,
        label: layerLabel(o),
      }))
    );
  }, [layerLabel]);

  // ===== 响应式恢复画布（fabric 就绪后执行一次） =====
  const restoredRef = useRef(false);
  useEffect(() => {
    if (!storyboardCanvasState || restoredRef.current) return;
    const canvas = fabricRef.current;
    if (!canvas) return;
    restoredRef.current = true;
    try {
      canvas.loadFromJSON(JSON.parse(storyboardCanvasState), () => {
        canvas.renderAll();
        refreshLayers();
      });
    } catch {
      // 恢复失败从零开始
    }
  }, [storyboardCanvasState, refreshLayers]);

  const clickLayer = useCallback(
    (id: string) => {
      const canvas = fabricRef.current;
      if (!canvas) return;
      const obj = canvas
        .getObjects()
        .find((o: any) => ((o as any).customId || o.id) === id);
      if (!obj) return;
      canvas.setActiveObject(obj);
      canvas.renderAll();
      updateSelectionInfo(obj);
    },
    [updateSelectionInfo]
  );

  const changeZoom = useCallback(
    (delta: number) => {
      const fabric = fabricLibRef.current;
      if (!fabric) return;
      const canvas = fabricRef.current;
      if (!canvas) return;
      const newZoom = Math.min(300, Math.max(20, zoom + delta));
      const center = canvas.getVpCenter
        ? canvas.getVpCenter()
        : { x: CANVAS_WIDTH / 2, y: CANVAS_HEIGHT / 2 };
      canvas.zoomToPoint(
        new fabric.Point(center.x, center.y),
        newZoom / 100
      );
      setZoom(newZoom);
    },
    [zoom]
  );

  // ===== 初始化画布（fabric 客户端动态加载，避免服务端构建期 require node-canvas/jsdom） =====
  useEffect(() => {
    const el = canvasElRef.current;
    if (!el) return;
    let disposed = false;
    let canvas: any = null;
    let handleKeyDown: (e: KeyboardEvent) => void = () => {};
    let handleKeyUp: (e: KeyboardEvent) => void = () => {};

    getFabric()
      .then((fabric) => {
        if (disposed) return;
        fabricLibRef.current = fabric;

        canvas = new fabric.Canvas(el, {
          width: CANVAS_WIDTH,
          height: CANVAS_HEIGHT,
          backgroundColor: "#f8f9fa",
          selection: true,
          preserveObjectStacking: true,
          stopContextMenu: true,
          fireRightClick: true,
        });

        fabricRef.current = canvas;

        drawGrid(canvas, fabric);

        // 选中样式
        fabric.Object.prototype.set({
          borderColor: "#5c7cfa",
          cornerColor: "#5c7cfa",
          cornerStrokeColor: "#5c7cfa",
          cornerSize: 10,
          cornerStyle: "circle",
          transparentCorners: false,
          borderScaleFactor: 1.5,
        });

        // ---- 事件绑定 ----
        canvas.on("object:modified", () => {
          saveStateToUndoStack();
          const active = canvas.getActiveObject();
          if (active) updateSelectionInfo(active);
          syncCanvasState();
        });

        canvas.on("selection:created", (e: any) => {
          updateSelectionInfo(e.selected?.[0] ?? null);
        });
        canvas.on("selection:updated", (e: any) => {
          updateSelectionInfo(e.selected?.[0] ?? null);
        });
        canvas.on("selection:cleared", () => {
          updateSelectionInfo(null);
        });

        // 双击文字编辑
        canvas.on("mouse:dblclick", (e: any) => {
          const target = e.target;
          if (target && target.type === "i-text") {
            canvas.setActiveObject(target);
            (target as any).enterEditing();
          }
        });

        // 滚轮缩放（以鼠标位置为中心）
        canvas.on("mouse:wheel", (opt: any) => {
          const evt = opt.e as WheelEvent;
          evt.preventDefault();
          evt.stopPropagation();

          const delta = evt.deltaY;
          // 以画布当前缩放为基准（修复连续滚动时闭包旧值导致缩放不准）
          const currentZoom = Math.round(canvas.getZoom() * 100);
          let newZoom = currentZoom;
          if (delta > 0) {
            newZoom = Math.max(20, currentZoom - 5);
          } else {
            newZoom = Math.min(300, currentZoom + 5);
          }

          const point = new fabric.Point(evt.offsetX, evt.offsetY);
          canvas.zoomToPoint(point, newZoom / 100);
          setZoom(newZoom);
        });

        // 空格键 + 拖拽平移
        handleKeyDown = (e: KeyboardEvent) => {
          if (e.code === "Space" && !e.repeat) {
            e.preventDefault();
            spaceDownRef.current = true;
            canvas.selection = false;
            canvas.defaultCursor = "grab";
            canvas.hoverCursor = "grab";
            (canvasElRef.current as HTMLCanvasElement).style.cursor = "grab";
            canvas.getObjects().forEach((o: any) => {
              o.selectable = false;
              o.evented = false;
            });
            canvas.renderAll();
          }
        };

        handleKeyUp = (e: KeyboardEvent) => {
          if (e.code === "Space") {
            spaceDownRef.current = false;
            isPanningRef.current = false;
            lastPanPointRef.current = null;
            canvas.selection = true;
            canvas.defaultCursor = "default";
            canvas.hoverCursor = "move";
            (canvasElRef.current as HTMLCanvasElement).style.cursor = "default";
            canvas.getObjects().forEach((o: any) => {
              o.selectable = true;
              o.evented = true;
            });
            canvas.renderAll();
          }
        };

        window.addEventListener("keydown", handleKeyDown);
        window.addEventListener("keyup", handleKeyUp);

        canvas.on("mouse:down", (opt: any) => {
          if (spaceDownRef.current) {
            isPanningRef.current = true;
            lastPanPointRef.current = { x: opt.e.clientX, y: opt.e.clientY };
            (canvasElRef.current as HTMLCanvasElement).style.cursor = "grabbing";
          }
        });

        canvas.on("mouse:move", (opt: any) => {
          if (isPanningRef.current && lastPanPointRef.current) {
            const vpt = canvas.viewportTransform!;
            vpt[4] += opt.e.clientX - lastPanPointRef.current.x;
            vpt[5] += opt.e.clientY - lastPanPointRef.current.y;
            lastPanPointRef.current = { x: opt.e.clientX, y: opt.e.clientY };
            canvas.requestRenderAll();
          } else if (spaceDownRef.current) {
            (canvasElRef.current as HTMLCanvasElement).style.cursor = "grab";
          }
        });

        canvas.on("mouse:up", () => {
          if (isPanningRef.current) {
            isPanningRef.current = false;
            lastPanPointRef.current = null;
            (canvasElRef.current as HTMLCanvasElement).style.cursor = spaceDownRef.current
              ? "grab"
              : "default";
          }
        });

        // 图层列表联动 + 画布状态同步
        canvas.on("object:added", () => {
          refreshLayers();
          syncCanvasState();
        });
        canvas.on("object:removed", () => {
          refreshLayers();
          syncCanvasState();
        });
        refreshLayers();
        setFabricReady(true);

        // 保存初始状态（已从后端恢复则跳过）
        if (!useProjectStore.getState().storyboardCanvasState) {
          try {
            const json = JSON.stringify(
              canvas.toJSON(["objectType", "customId", "sceneNumber", "excludeFromExport"])
            );
            pushStoryboardUndo(json);
          } catch {
            // silent
          }
        }
      })
      .catch((err: any) => {
        if (!disposed) {
          console.error("fabric 画布库加载失败，请刷新重试", err?.message ?? err);
        }
      });

    return () => {
      disposed = true;
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      if (canvas) canvas.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ===== 工具栏：添加对象 =====

  const addText = useCallback(() => {
    const fabric = fabricLibRef.current;
    if (!fabric) return;
    const canvas = fabricRef.current;
    if (!canvas) return;
    saveStateToUndoStack();
    const customId = generateObjectId();
    const text = new fabric.IText("双击编辑文字", {
      left: CANVAS_WIDTH / 2 - 60,
      top: CANVAS_HEIGHT / 2 - 15,
      fontSize: 24,
      fill: "#343a40",
      fontFamily: "Inter, sans-serif",
      objectType: "text",
      customId,
    } as any);
    canvas.add(text);
    canvas.setActiveObject(text);
    canvas.renderAll();
    updateSelectionInfo(text);
  }, [saveStateToUndoStack, updateSelectionInfo]);

  const addSceneBox = useCallback(() => {
    const fabric = fabricLibRef.current;
    if (!fabric) return;
    const canvas = fabricRef.current;
    if (!canvas) return;
    saveStateToUndoStack();
    const existing = canvas
      .getObjects()
      .filter((o: any) => (o as any).objectType === "sceneBox").length;
    const group = buildSceneBox(existing + 1, sceneCount, fabric);
    (group as any).customId = generateObjectId();
    canvas.add(group);
    canvas.setActiveObject(group);
    canvas.renderAll();
    updateSelectionInfo(group);
  }, [saveStateToUndoStack, updateSelectionInfo, sceneCount]);

  const addCircle = useCallback(() => {
    const fabric = fabricLibRef.current;
    if (!fabric) return;
    const canvas = fabricRef.current;
    if (!canvas) return;
    saveStateToUndoStack();
    const customId = generateObjectId();
    const circle = new fabric.Circle({
      left: CANVAS_WIDTH / 2 - 35,
      top: CANVAS_HEIGHT / 2 - 35,
      radius: 35,
      fill: "rgba(92, 124, 250, 0.3)",
      stroke: "#5c7cfa",
      strokeWidth: 2,
      objectType: "circle",
      customId,
    } as any);
    canvas.add(circle);
    canvas.setActiveObject(circle);
    canvas.renderAll();
    updateSelectionInfo(circle);
  }, [saveStateToUndoStack, updateSelectionInfo]);

  const addArrow = useCallback(() => {
    const fabric = fabricLibRef.current;
    if (!fabric) return;
    const canvas = fabricRef.current;
    if (!canvas) return;
    saveStateToUndoStack();
    const customId = generateObjectId();
    const points: { x: number; y: number }[] = [
      { x: 0, y: 0 }, { x: 150, y: 0 }, { x: 140, y: -8 },
      { x: 160, y: 0 }, { x: 140, y: 8 }, { x: 150, y: 0 },
    ];
    const arrow = new fabric.Polyline(points, {
      left: CANVAS_WIDTH / 2 - 80,
      top: CANVAS_HEIGHT / 2,
      fill: "#5c7cfa",
      stroke: "#5c7cfa",
      strokeWidth: 2,
      objectType: "arrow",
      customId,
    } as any);
    canvas.add(arrow);
    canvas.setActiveObject(arrow);
    canvas.renderAll();
    updateSelectionInfo(arrow);
  }, [saveStateToUndoStack, updateSelectionInfo]);

  const handleUploadImage = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const fabric = fabricLibRef.current;
      if (!fabric) return;
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        const dataUrl = ev.target?.result as string;
        fabric.Image.fromURL(dataUrl, (img: any) => {
          const canvas = fabricRef.current;
          if (!canvas) return;
          saveStateToUndoStack();
          const maxWidth = CANVAS_WIDTH * 0.6;
          const maxHeight = CANVAS_HEIGHT * 0.6;
          if ((img.width ?? 0) > maxWidth || (img.height ?? 0) > maxHeight) {
            const scale = Math.min(
              maxWidth / (img.width ?? 1),
              maxHeight / (img.height ?? 1)
            );
            img.scale(scale);
          }
          (img as any).customId = generateObjectId();
          (img as any).objectType = "image";
          img.set({
            left:
              CANVAS_WIDTH / 2 - ((img.width ?? 0) * (img.scaleX ?? 1)) / 2,
            top:
              CANVAS_HEIGHT / 2 - ((img.height ?? 0) * (img.scaleY ?? 1)) / 2,
          });
          canvas.add(img);
          canvas.setActiveObject(img);
          canvas.renderAll();
          updateSelectionInfo(img);
        });
      };
      reader.readAsDataURL(file);
      e.target.value = "";
    },
    [saveStateToUndoStack, updateSelectionInfo]
  );

  const deleteSelected = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    const active = canvas.getActiveObject();
    if (!active) return;
    saveStateToUndoStack();
    canvas.remove(active);
    canvas.discardActiveObject();
    canvas.renderAll();
    updateSelectionInfo(null);
  }, [saveStateToUndoStack, updateSelectionInfo]);

  // ===== 属性面板操作 =====

  const updateNumericProperty = useCallback(
    (key: "left" | "top" | "angle" | "opacity", rawValue: string) => {
      const value = parseFloat(rawValue);
      if (isNaN(value)) return;
      const canvas = fabricRef.current;
      if (!canvas) return;
      const active = canvas.getActiveObject();
      if (!active) return;
      saveStateToUndoStack();
      active.set(key, value);
      active.setCoords();
      canvas.renderAll();
      updateSelectionInfo(active);
      syncCanvasState();
    },
    [saveStateToUndoStack, updateSelectionInfo, syncCanvasState]
  );

  const updateSliderProperty = useCallback(
    (key: "angle" | "opacity", value: number) => {
      const canvas = fabricRef.current;
      if (!canvas) return;
      const active = canvas.getActiveObject();
      if (!active) return;
      saveStateToUndoStack();
      active.set(key, value);
      active.setCoords();
      canvas.renderAll();
      updateSelectionInfo(active);
      syncCanvasState();
    },
    [saveStateToUndoStack, updateSelectionInfo, syncCanvasState]
  );

  const updateSizeInput = useCallback(
    (rawValue: string, isWidth: boolean) => {
      const canvas = fabricRef.current;
      if (!canvas) return;
      const active = canvas.getActiveObject();
      if (!active) return;
      const value = parseFloat(rawValue);
      if (isNaN(value) || value <= 0) return;
      saveStateToUndoStack();
      if (isWidth) {
        active.set("scaleX", value / (active.width ?? 1));
      } else {
        active.set("scaleY", value / (active.height ?? 1));
      }
      active.setCoords();
      canvas.renderAll();
      updateSelectionInfo(active);
      syncCanvasState();
    },
    [saveStateToUndoStack, updateSelectionInfo, syncCanvasState]
  );

  const moveLayer = useCallback(
    (direction: "up" | "down" | "top" | "bottom") => {
      const canvas = fabricRef.current;
      if (!canvas) return;
      const active = canvas.getActiveObject();
      if (!active) return;
      saveStateToUndoStack();
      switch (direction) {
        case "up":
          canvas.bringForward(active);
          break;
        case "down":
          canvas.sendBackwards(active);
          break;
        case "top":
          canvas.bringToFront(active);
          break;
        case "bottom":
          canvas.sendToBack(active);
          break;
      }
      canvas.discardActiveObject();
      canvas.setActiveObject(active);
      canvas.renderAll();
      syncCanvasState();
    },
    [saveStateToUndoStack, syncCanvasState]
  );

  // ===== 撤销/重做 =====

  const handleUndo = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    // 先把当前画布状态同步进 store，undoStoryboard 才会把它压入 redo 栈
    const current = JSON.stringify(
      canvas.toJSON(["objectType", "customId", "sceneNumber", "excludeFromExport"])
    );
    setStoryboardCanvasState(current);
    const prev = undoStoryboard();
    if (prev) {
      canvas.loadFromJSON(JSON.parse(prev), () => {
        canvas.renderAll();
        updateSelectionInfo(null);
        refreshLayers();
      });
    }
  }, [undoStoryboard, updateSelectionInfo, refreshLayers, setStoryboardCanvasState]);

  const handleRedo = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    // 同步当前状态，redoStoryboard 才会把它压回 undo 栈
    const current = JSON.stringify(
      canvas.toJSON(["objectType", "customId", "sceneNumber", "excludeFromExport"])
    );
    setStoryboardCanvasState(current);
    const next = redoStoryboard();
    if (next) {
      canvas.loadFromJSON(JSON.parse(next), () => {
        canvas.renderAll();
        updateSelectionInfo(null);
        refreshLayers();
      });
    }
  }, [redoStoryboard, updateSelectionInfo, refreshLayers, setStoryboardCanvasState]);

  const handleSaveJSON = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    try {
      const json = JSON.stringify(
        canvas.toJSON(["objectType", "customId", "sceneNumber", "excludeFromExport"]),
        null,
        2
      );
      setStoryboardCanvasState(json);
      saveStateToUndoStack();
    } catch {
      // silent
    }
  }, [setStoryboardCanvasState, saveStateToUndoStack]);

  const handleExportPNG = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    const dataUrl = canvas.toDataURL({ format: "png", multiplier: 2 });
    const link = document.createElement("a");
    link.download = `storyboard_${Date.now()}.png`;
    link.href = dataUrl;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, []);

  const handleResetZoom = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    canvas.setZoom(1);
    canvas.renderAll();
    setZoom(100);
  }, []);

  // ===== 快捷键 =====
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      const isCtrl = e.ctrlKey || e.metaKey;
      if (isCtrl && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      } else if (isCtrl && (e.key === "Z" || (e.key === "z" && e.shiftKey))) {
        e.preventDefault();
        handleRedo();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        const activeEl = document.activeElement;
        if (activeEl?.tagName === "INPUT" || activeEl?.tagName === "TEXTAREA") return;
        deleteSelected();
      }
    };
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, [handleUndo, handleRedo, deleteSelected]);

  // ===== 渲染 =====
  const computedWidth = selectedInfo
    ? (selectedInfo.width ?? 0)
    : 0;
  const computedHeight = selectedInfo
    ? (selectedInfo.height ?? 0)
    : 0;

  return (
    <div className="flex h-full min-h-0">
      {/* ===== 左侧工具栏 + 图层 ===== */}
      <div className="w-56 border-r border-surface-200 bg-white flex-shrink-0 flex flex-col">
        <div className="p-3 space-y-1.5 border-b border-surface-100">
          <p className="text-xs text-surface-400 font-medium mb-2">添加元素</p>
          <button
            onClick={addText}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-surface-600 rounded-lg hover:bg-surface-100 hover:text-primary-600 transition-colors"
          >
            <Type size={16} />
            文字
          </button>
          <button
            onClick={addSceneBox}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-surface-600 rounded-lg hover:bg-surface-100 hover:text-primary-600 transition-colors"
          >
            <Square size={16} />
            场景框
          </button>
          <button
            onClick={addCircle}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-surface-600 rounded-lg hover:bg-surface-100 hover:text-primary-600 transition-colors"
          >
            <Circle size={16} />
            圆形
          </button>
          <button
            onClick={addArrow}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-surface-600 rounded-lg hover:bg-surface-100 hover:text-primary-600 transition-colors"
          >
            <ArrowRight size={16} />
            箭头
          </button>
          <button
            onClick={handleUploadImage}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-surface-600 rounded-lg hover:bg-surface-100 hover:text-primary-600 transition-colors"
          >
            <ImagePlus size={16} />
            上传图片
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          <p className="text-xs text-surface-400 font-medium mb-2">图层</p>
          {layers.length === 0 ? (
            <p className="text-xs text-surface-300 text-center py-6">
              暂无对象，点击上方按钮添加
            </p>
          ) : (
            <div className="space-y-1">
              {layers.map((layer) => (
                <button
                  key={layer.id}
                  onClick={() => clickLayer(layer.id)}
                  className={`w-full flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-md transition-colors ${
                    selectedInfo?.id === layer.id
                      ? "bg-primary-50 text-primary-700 border border-primary-200"
                      : "text-surface-600 hover:bg-surface-100 border border-transparent"
                  }`}
                >
                  {layer.type === "sceneBox" ? (
                    <Square size={12} />
                  ) : layer.type === "circle" ? (
                    <Circle size={12} />
                  ) : layer.type === "arrow" ? (
                    <ArrowRight size={12} />
                  ) : layer.type === "image" ? (
                    <ImagePlus size={12} />
                  ) : (
                    <Type size={12} />
                  )}
                  {layer.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ===== 中栏：画布 ===== */}
      <div className="flex-1 min-w-0 flex flex-col bg-surface-50">
        <div className="flex items-center justify-between px-4 py-2 border-b border-surface-200 bg-white flex-shrink-0">
          <div className="flex items-center gap-2">
            <button
              onClick={() => changeZoom(-5)}
              title="缩小"
              className="w-7 h-7 flex items-center justify-center rounded-md text-surface-500 hover:bg-surface-100 transition-colors"
            >
              <ChevronDown size={16} />
            </button>
            <span className="text-xs text-surface-600 w-12 text-center">
              {zoom}%
            </span>
            <button
              onClick={() => changeZoom(5)}
              title="放大"
              className="w-7 h-7 flex items-center justify-center rounded-md text-surface-500 hover:bg-surface-100 transition-colors"
            >
              <ChevronUp size={16} />
            </button>
            <button
              onClick={handleResetZoom}
              title="重置缩放"
              className="text-xs text-surface-400 hover:text-primary-600 ml-1"
            >
              重置
            </button>
          </div>
          <div className="flex items-center gap-1.5">
            <ToolButton
              icon={<Undo2 size={16} />}
              label="撤销 (Ctrl+Z)"
              onClick={handleUndo}
              className={!canUndo ? "opacity-30 pointer-events-none" : ""}
            />
            <ToolButton
              icon={<Redo2 size={16} />}
              label="重做 (Ctrl+Shift+Z)"
              onClick={handleRedo}
              className={!canRedo ? "opacity-30 pointer-events-none" : ""}
            />
            <div className="w-px h-5 bg-surface-200 mx-1" />
            <ToolButton
              icon={<Save size={16} />}
              label="保存画布"
              onClick={handleSaveJSON}
            />
            {saveStatus === "saving" && (
              <span className="text-[11px] text-surface-400">保存中…</span>
            )}
            {saveStatus === "saved" && (
              <span className="text-[11px] text-emerald-600">已自动保存</span>
            )}
            {saveStatus === "failed" && (
              <span className="text-[11px] text-red-500">保存失败</span>
            )}
            <ToolButton
              icon={<Download size={16} />}
              label="导出 PNG"
              onClick={handleExportPNG}
            />
            <ToolButton
              icon={<Trash2 size={16} />}
              label="删除选中 (Del)"
              onClick={deleteSelected}
              className={!selectedInfo ? "opacity-30 pointer-events-none" : ""}
            />
          </div>
        </div>

        <div className="flex-1 overflow-auto p-4 flex items-start justify-center">
          <div
            className="relative shadow-lg rounded-sm"
            style={{ width: CANVAS_WIDTH, height: CANVAS_HEIGHT }}
          >
            <canvas ref={canvasElRef} style={{ width: CANVAS_WIDTH, height: CANVAS_HEIGHT }} />
            {!fabricReady && (
              <div className="absolute inset-0 flex items-center justify-center text-surface-400 text-sm bg-white/80">
                画布加载中...
              </div>
            )}
          </div>
        </div>
        <div className="px-4 py-1.5 text-[11px] text-surface-400 border-t border-surface-200 bg-white flex items-center gap-3 flex-shrink-0">
          <span>空格 + 拖拽平移</span>
          <span>·</span>
          <span>滚轮缩放</span>
          <span>·</span>
          <span>双击文字可编辑</span>
          <span>·</span>
          <span>画布 1280×720 (16:9)</span>
        </div>
      </div>

      {/* ===== 右栏：属性面板 ===== */}
      <div className="w-60 border-l border-surface-200 bg-white flex-shrink-0 p-4 overflow-y-auto">
        <p className="text-xs text-surface-400 font-medium mb-3">属性</p>
        {selectedInfo ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[11px] text-surface-400 mb-1">X</label>
                <input
                  type="number"
                  value={Math.round(selectedInfo.left)}
                  onChange={(e) => updateNumericProperty("left", e.target.value)}
                  className="input-field !py-1.5 text-xs"
                />
              </div>
              <div>
                <label className="block text-[11px] text-surface-400 mb-1">Y</label>
                <input
                  type="number"
                  value={Math.round(selectedInfo.top)}
                  onChange={(e) => updateNumericProperty("top", e.target.value)}
                  className="input-field !py-1.5 text-xs"
                />
              </div>
              <div>
                <label className="block text-[11px] text-surface-400 mb-1">宽</label>
                <input
                  type="number"
                  value={Math.round(computedWidth)}
                  onChange={(e) => updateSizeInput(e.target.value, true)}
                  className="input-field !py-1.5 text-xs"
                />
              </div>
              <div>
                <label className="block text-[11px] text-surface-400 mb-1">高</label>
                <input
                  type="number"
                  value={Math.round(computedHeight)}
                  onChange={(e) => updateSizeInput(e.target.value, false)}
                  className="input-field !py-1.5 text-xs"
                />
              </div>
            </div>

            <div>
              <label className="block text-[11px] text-surface-400 mb-1">
                角度 {Math.round(selectedInfo.angle)}°
              </label>
              <input
                type="range"
                min={-180}
                max={180}
                value={selectedInfo.angle}
                onChange={(e) =>
                  updateSliderProperty("angle", parseFloat(e.target.value))
                }
                className="w-full"
              />
            </div>
            <div>
              <label className="block text-[11px] text-surface-400 mb-1">
                不透明度 {Math.round(selectedInfo.opacity)}%
              </label>
              <input
                type="range"
                min={10}
                max={100}
                value={selectedInfo.opacity}
                onChange={(e) =>
                  updateSliderProperty("opacity", parseFloat(e.target.value))
                }
                className="w-full"
              />
            </div>

            <div>
              <p className="text-[11px] text-surface-400 mb-1.5">图层顺序</p>
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => moveLayer("up")}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] text-surface-600 bg-surface-100 rounded-md hover:bg-surface-200 transition-colors"
                >
                  <MoveUp size={11} /> 上移
                </button>
                <button
                  onClick={() => moveLayer("down")}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] text-surface-600 bg-surface-100 rounded-md hover:bg-surface-200 transition-colors"
                >
                  <MoveDown size={11} /> 下移
                </button>
                <button
                  onClick={() => moveLayer("top")}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] text-surface-600 bg-surface-100 rounded-md hover:bg-surface-200 transition-colors"
                >
                  <MoveUp size={11} /> 置顶
                </button>
                <button
                  onClick={() => moveLayer("bottom")}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] text-surface-600 bg-surface-100 rounded-md hover:bg-surface-200 transition-colors"
                >
                  <MoveDown size={11} /> 置底
                </button>
              </div>
            </div>

            <div className="pt-2 border-t border-surface-100">
              <button
                onClick={deleteSelected}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs text-red-600 bg-red-50 rounded-md hover:bg-red-100 transition-colors"
              >
                <Trash2 size={13} />
                删除选中对象
              </button>
            </div>
          </div>
        ) : (
          <p className="text-xs text-surface-300 text-center py-8 leading-relaxed">
            在画布上点击或添加对象
            <br />
            即可编辑属性
          </p>
        )}
      </div>
    </div>
  );
}

// ===== 工具按钮子组件 =====

function ToolButton({
  icon,
  label,
  onClick,
  className = "",
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`w-9 h-9 flex items-center justify-center rounded-lg text-surface-500 hover:text-surface-700 hover:bg-surface-100 transition-colors ${className}`}
    >
      {icon}
    </button>
  );
}

export default StoryboardCanvas;
