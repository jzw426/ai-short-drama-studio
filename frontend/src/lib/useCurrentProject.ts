"use client";

import { useEffect, useState } from "react";
import { projectApi } from "./api";
import { useProjectStore } from "@/store/useProjectStore";
import type { Project } from "@/types";

/**
 * 取当前项目；若本地没有（新浏览器 / 清了 localStorage），自动拉一次项目列表并选中第一个。
 *
 * 页面不再假设 currentProject 一定存在 —— 之前 studio 下几个页面直接在 null 上取 .id，
 * 刷新后白屏只留一句 "请先选择项目"，用户根本不知道该去哪选。
 */
export function useCurrentProject() {
  const currentProject = useProjectStore((s) => s.currentProject);
  const setProjects = useProjectStore((s) => s.setProjects);
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (currentProject) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const list = (await projectApi.list()) as unknown as Project[];
        if (cancelled) return;
        if (Array.isArray(list) && list.length > 0) {
          setProjects(list);
          setCurrentProject(list[0]);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "加载项目失败");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentProject, setProjects, setCurrentProject]);

  return { project: currentProject, loading, error };
}
