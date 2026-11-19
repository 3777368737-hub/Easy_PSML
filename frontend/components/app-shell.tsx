"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import Icon, { type IconName } from "./icon";

const steps: {
  href: string;
  title: string;
  subtitle: string;
  icon: IconName;
}[] = [
  {
    href: "/profile",
    title: "背景信息",
    subtitle: "整理你的独特经历",
    icon: "user",
  },
  {
    href: "/program",
    title: "项目分析",
    subtitle: "找到经历与目标的连接",
    icon: "target",
  },
  {
    href: "/story",
    title: "故事挖掘",
    subtitle: "让真实细节成为证据",
    icon: "chat",
  },
  {
    href: "/result",
    title: "文书工作台",
    subtitle: "从叙事大纲到英文草稿",
    icon: "file",
  },
];
export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname().replace(/\/$/, "") || "/";
  const current = steps.findIndex((step) => step.href === pathname);
  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">
        跳到主要内容
      </a>
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="GradPilot 首页">
          <span className="brand-mark">
            <Icon name="compass" size={25} />
          </span>
          <span>
            GradPilot<span className="brand-sub">YOUR STORY. YOUR FUTURE.</span>
          </span>
        </Link>
        <nav aria-label="主导航" className="side-nav">
          <Link
            href="/"
            className={`nav-item ${pathname === "/" ? "active" : ""}`}
            aria-current={pathname === "/" ? "page" : undefined}
          >
            <Icon name="home" />
            <span>申请概览</span>
          </Link>
          <p className="nav-label">我的申请流程</p>
          {steps.map((step, i) => (
            <Link
              key={step.href}
              href={step.href}
              className={`nav-item ${pathname === step.href ? "active" : ""}`}
              aria-current={pathname === step.href ? "page" : undefined}
            >
              <Icon name={step.icon} />
              <span>{step.title}</span>
              <span className="nav-index">0{i + 1}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-note">
          <Icon name="spark" />
          <h3>好文书，源于真实的你。</h3>
          <p>从一段经历开始，慢慢找到属于你的表达。</p>
        </div>
        <div className="sidebar-foot">
          <span className="avatar">G</span>
          <div>
            申请者工作空间<small>AI 辅助 · 由你确认</small>
          </div>
        </div>
      </aside>
      <div className="app-content">
        <header className="workspace-header">
          <div className="breadcrumb">
            我的工作空间 <span>/</span>{" "}
            <strong>{current < 0 ? "申请概览" : steps[current].title}</strong>
          </div>
          <span className="header-tag">
            <Icon name="spark" size={16} /> AI 文书助手
          </span>
        </header>
        {current >= 0 && (
          <nav className="workflow-steps" aria-label="申请步骤">
            {steps.map((step, i) => (
              <Link
                href={step.href}
                key={step.href}
                className={`workflow-step ${i === current ? "current" : ""}`}
                aria-current={i === current ? "step" : undefined}
              >
                <span className="step-number">{i + 1}</span>
                <span>
                  <strong>{step.title}</strong>
                  <small>{step.subtitle}</small>
                </span>
              </Link>
            ))}
          </nav>
        )}
        <div id="main-content" tabIndex={-1}>
          {children}
        </div>
        <footer className="workspace-footer">
          <span>GradPilot · 为你的下一程</span>
          <span>AI 辅助写作，请核实内容并保留个人表达。</span>
        </footer>
      </div>
    </div>
  );
}
