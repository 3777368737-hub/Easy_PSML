import "./globals.css";
import type { ReactNode } from "react";
import StorageMigration from "@/lib/storage-migration";
import AppShell from "@/components/app-shell";
import VoiceInputButton from "@/components/voice-input-button";
export const metadata = {
  title: "GradPilot | 你的申请文书工作台",
  description: "从真实经历出发，整理背景、分析项目、挖掘故事，完成申请文书。",
};
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <StorageMigration />
        <AppShell>{children}</AppShell>
        <VoiceInputButton />
      </body>
    </html>
  );
}
