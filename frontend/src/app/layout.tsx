import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import Providers from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Short Drama Studio",
  description:
    "面向AI短剧创作者的一站式工作流平台 — 剧本工坊 · 分镜设计 · 角色管理 · 一键成片 · 素材库",
  keywords: ["AI短剧", "视频生成", "剧本创作", "分镜设计", "AI微短剧"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="font-sans antialiased bg-surface-50">
        <Providers>
          <ErrorBoundary>
            <AppShell>{children}</AppShell>
          </ErrorBoundary>
        </Providers>
      </body>
    </html>
  );
}
