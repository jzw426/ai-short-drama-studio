"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { Toaster } from "sonner";
import { useProjectStore } from "@/store/useProjectStore";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  // 初始化 store 从 localStorage 恢复
  useEffect(() => {
    const stored = localStorage.getItem("ai-drama-studio-store");
    if (stored) {
      try {
        const data = JSON.parse(stored);
        // 只恢复项目选择；剧本/分镜等业务数据一律以服务端为准
        useProjectStore.setState({
          projects: Array.isArray(data?.projects) ? data.projects : [],
          currentProject: data?.currentProject ?? null,
        });
      } catch {
        // 忽略解析错误
      }
    }
  }, []);

  // 监听 store 变化并持久化
  useEffect(() => {
    const unsubscribe = useProjectStore.subscribe((state) => {
      const { projects, currentProject } = state;
      localStorage.setItem(
        "ai-drama-studio-store",
        JSON.stringify({ projects, currentProject })
      );
    });
    return unsubscribe;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  );
}
