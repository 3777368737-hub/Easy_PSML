"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import Icon, { type IconName } from "./icon";

type NavItem = {
  href: string;
  title: string;
  subtitle?: string;
  index?: string;
  icon: IconName;
};

const workflowSteps: NavItem[] = [
  {
    href: "/profile",
    title: "背景资料",
    subtitle: "整理个人经历",
    index: "01",
    icon: "user",
  },
  {
    href: "/program",
    title: "项目分析",
    subtitle: "匹配申请要求",
    index: "02",
    icon: "target",
  },
  {
    href: "/story",
    title: "故事访谈",
    subtitle: "提炼真实细节",
    index: "03",
    icon: "chat",
  },
  {
    href: "/result",
    title: "文书编辑",
    subtitle: "大纲、草稿与审核",
    index: "04",
    icon: "file",
  },
];

const pageLabels: Record<string, string> = {
  "/": "工作台",
  "/profile": "背景资料",
  "/program": "项目分析",
  "/story": "故事访谈",
  "/result": "文书编辑",
  "/batch": "批量生成",
  "/library": "申请项目",
};

function navClass(active: boolean): string {
  return `nav-item ${active ? "active" : ""}`;
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname()?.replace(/\/$/, "") || "/";
  const [menuOpen, setMenuOpen] = useState(false);
  const pageLabel = pageLabels[pathname] || "工作台";
  const workflowIndex = workflowSteps.findIndex(
    (step) => step.href === pathname,
  );

  useEffect(() => {
    if (!menuOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  function closeMenu() {
    setMenuOpen(false);
  }

  return (
    <div className={`app-shell ${menuOpen ? "menu-open" : ""}`}>
      <a href="#main-content" className="skip-link">
        跳到主要内容
      </a>

      <button
        type="button"
        className="mobile-nav-scrim"
        aria-label="关闭导航"
        tabIndex={menuOpen ? 0 : -1}
        onClick={closeMenu}
      />

      <aside id="primary-navigation" className="sidebar">
        <div className="sidebar-brand-row">
          <Link
            className="brand"
            href="/"
            aria-label="GradPilot 工作台"
            onClick={closeMenu}
          >
            <span className="brand-mark">
              <Icon name="compass" size={24} />
            </span>
            <span>
              GradPilot
              <span className="brand-sub">APPLICATION STUDIO</span>
            </span>
          </Link>
          <button
            type="button"
            className="mobile-nav-close"
            aria-label="关闭导航"
            onClick={closeMenu}
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        <nav aria-label="主导航" className="side-nav">
          <div className="nav-group">
            <p className="nav-label">工作区</p>
            <Link
              href="/"
              className={navClass(pathname === "/")}
              aria-current={pathname === "/" ? "page" : undefined}
              onClick={closeMenu}
            >
              <Icon name="home" />
              <span>工作台</span>
              <span className="nav-index">HOME</span>
            </Link>
            <Link
              href="/library"
              className={navClass(pathname === "/library")}
              aria-current={pathname === "/library" ? "page" : undefined}
              onClick={closeMenu}
            >
              <Icon name="layers" />
              <span>申请项目</span>
              <span className="nav-index">ALL</span>
            </Link>
          </div>

          <div className="nav-group">
            <p className="nav-label">单篇流程</p>
            {workflowSteps.map((step) => (
              <Link
                key={step.href}
                href={step.href}
                className={navClass(pathname === step.href)}
                aria-current={pathname === step.href ? "page" : undefined}
                onClick={closeMenu}
              >
                <Icon name={step.icon} />
                <span>{step.title}</span>
                <span className="nav-index">{step.index}</span>
              </Link>
            ))}
          </div>

          <div className="nav-group">
            <p className="nav-label">效率工具</p>
            <Link
              href="/batch"
              className={navClass(pathname === "/batch")}
              aria-current={pathname === "/batch" ? "page" : undefined}
              onClick={closeMenu}
            >
              <Icon name="folder" />
              <span>批量生成</span>
              <span className="nav-index">PS / ML</span>
            </Link>
          </div>
        </nav>

        <div className="sidebar-note">
          <Icon name="spark" size={18} />
          <h3>先把申请链路搭清楚</h3>
          <p>背景、项目、故事与文书保持绑定，后续修改更容易追溯。</p>
        </div>
        <div className="sidebar-foot">
          <span className="avatar">G</span>
          <div>
            申请者工作区
            <small>AI 辅助 · 由你确认</small>
          </div>
        </div>
      </aside>

      <div className="app-content">
        <header className="workspace-header">
          <div className="workspace-header-start">
            <button
              type="button"
              className="mobile-menu-button"
              aria-controls="primary-navigation"
              aria-expanded={menuOpen}
              aria-label="打开导航"
              onClick={() => setMenuOpen(true)}
            >
              <Icon name="menu" size={20} />
            </button>
            <div className="breadcrumb">
              <span>工作区</span>
              <Icon name="arrow-right" size={13} />
              <strong>{pageLabel}</strong>
            </div>
            <strong className="mobile-page-title">{pageLabel}</strong>
          </div>
          <div className="header-context">
            {workflowIndex >= 0 ? (
              <span className="header-step">
                第 {workflowIndex + 1} / {workflowSteps.length} 步
              </span>
            ) : null}
            <span className="header-tag">
              <Icon name="check" size={15} /> AI 辅助 · 由你确认
            </span>
          </div>
        </header>

        <div id="main-content" tabIndex={-1}>
          {children}
        </div>

        <footer className="workspace-footer">
          <span>GradPilot · Application Studio</span>
          <span>生成内容请核对事实，并保留你的个人表达。</span>
        </footer>
      </div>
    </div>
  );
}
