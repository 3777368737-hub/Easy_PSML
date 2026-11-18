import './globals.css';
import Link from 'next/link';
import type { ReactNode } from 'react';
import StorageMigration from '@/lib/storage-migration';

export const metadata = {
  title: 'GradPilot',
  description: '基于 DeepSeek 的研究生申请文书助手',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <StorageMigration />
        <header className="topbar">
          <div className="container topbar-inner">
            <Link href="/" className="brand">
              GradPilot
            </Link>
            <nav className="nav">
              <Link href="/profile">背景信息</Link>
              <Link href="/program">项目分析</Link>
              <Link href="/story">故事挖掘</Link>
              <Link href="/result">生成结果</Link>
            </nav>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
