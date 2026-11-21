"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Icon, { type IconName } from "@/components/icon";
import { apiFetch, readableError } from "@/lib/api";
import { loadState, STORAGE_KEYS } from "@/lib/storage";
import type {
  ApplicationProject,
  EssayProject,
  WorkspaceSnapshot,
} from "@/lib/types";

type NextAction = {
  href: string;
  label: string;
  icon: IconName;
};

function latestFirst<T extends { updated_at: string }>(items: T[]): T[] {
  return [...items].sort(
    (left, right) =>
      new Date(right.updated_at).getTime() -
      new Date(left.updated_at).getTime(),
  );
}

function projectStatus(project: EssayProject): string {
  if (project.status === "stale") return "需更新";
  if (project.status === "reviewed") return "已审核";
  if (project.status === "drafted") return "已有草稿";
  if (project.status === "outlined") return "已有大纲";
  if (project.status === "analyzed") return "已分析";
  return "待开始";
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
  });
}

export default function HomePage() {
  const [workspace, setWorkspace] = useState<WorkspaceSnapshot | null>(null);
  const [activeBackgroundId, setActiveBackgroundId] = useState("");
  const [activeApplicationProjectId, setActiveApplicationProjectId] =
    useState("");
  const [activeProjectId, setActiveProjectId] = useState("");
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    void apiFetch<WorkspaceSnapshot>("/api/workspace")
      .then((next) => {
        if (cancelled) return;
        setWorkspace(next);
        setActiveBackgroundId(
          loadState<string>(STORAGE_KEYS.activeBackgroundId) || "",
        );
        setActiveApplicationProjectId(
          loadState<string>(STORAGE_KEYS.activeApplicationProjectId) || "",
        );
        setActiveProjectId(
          loadState<string>(STORAGE_KEYS.activeProjectId) || "",
        );
        setError("");
      })
      .catch((requestError) => {
        if (cancelled) return;
        setError(readableError(requestError, "加载工作区失败"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const data = useMemo(() => {
    const backgrounds = workspace?.backgrounds || [];
    const applicationProjects = workspace?.application_projects || [];
    const stories = workspace?.stories || [];
    const essayProjects = workspace?.projects || [];
    const people = workspace?.persons || [];
    const currentBackground =
      backgrounds.find((item) => item.id === activeBackgroundId) ||
      latestFirst(backgrounds)[0] ||
      null;
    const matchingProjects = currentBackground
      ? applicationProjects.filter(
          (item) => item.background_instance_id === currentBackground.id,
        )
      : applicationProjects;
    const currentApplication =
      matchingProjects.find(
        (item) => item.id === activeApplicationProjectId,
      ) ||
      latestFirst(matchingProjects)[0] ||
      null;
    const currentStories = stories.filter(
      (story) =>
        story.background_instance_id === currentBackground?.id &&
        (!currentApplication ||
          !story.application_project_id ||
          story.application_project_id === currentApplication.id),
    );
    const readyStories = currentStories.filter(
      (story) => story.status === "ready",
    );
    const contextEssays = currentApplication
      ? essayProjects.filter(
          (project) =>
            project.application_project_id === currentApplication.id,
        )
      : essayProjects;
    const currentEssay =
      contextEssays.find((project) => project.id === activeProjectId) ||
      latestFirst(contextEssays)[0] ||
      null;
    const currentPerson = people.find(
      (person) => person.id === currentBackground?.person_id,
    );
    const recentProjects = latestFirst(applicationProjects).slice(0, 4);

    let nextAction: NextAction = {
      href: "/profile",
      label: "开始整理背景",
      icon: "user",
    };
    if (currentBackground && !currentApplication) {
      nextAction = {
        href: "/library",
        label: "添加申请项目",
        icon: "plus",
      };
    } else if (currentApplication && !readyStories.length) {
      nextAction = {
        href: "/library",
        label: "开始故事访谈",
        icon: "chat",
      };
    } else if (currentApplication && !currentEssay?.draft) {
      nextAction = {
        href: "/library",
        label: "装配并生成文书",
        icon: "file",
      };
    } else if (currentEssay?.draft) {
      nextAction = {
        href: "/result",
        label: "继续编辑文书",
        icon: "arrow-right",
      };
    }

    return {
      backgrounds,
      applicationProjects,
      stories,
      essayProjects,
      currentBackground,
      currentApplication,
      currentEssay,
      currentPerson,
      readyStories,
      recentProjects,
      nextAction,
    };
  }, [
    activeApplicationProjectId,
    activeBackgroundId,
    activeProjectId,
    workspace,
  ]);

  const completedDrafts = data.essayProjects.filter(
    (project) => Boolean(project.draft?.trim()),
  ).length;
  const metrics = [
    {
      label: "背景资料",
      value: data.backgrounds.length,
      detail: data.currentBackground?.resume_name || "还未建立",
      icon: "user" as IconName,
    },
    {
      label: "申请项目",
      value: data.applicationProjects.length,
      detail: data.currentApplication
        ? `${data.currentApplication.school_name} · ${data.currentApplication.program_name}`
        : data.applicationProjects.length
          ? `${data.applicationProjects.length} 个已记录项目`
          : "还未添加",
      icon: "target" as IconName,
    },
    {
      label: "可用故事",
      value: data.readyStories.length,
      detail: data.currentBackground
        ? `${data.stories.length} 个故事实例`
        : "访谈后自动沉淀",
      icon: "chat" as IconName,
    },
    {
      label: "文书项目",
      value: data.essayProjects.length,
      detail: `${completedDrafts} 篇已有英文草稿`,
      icon: "file" as IconName,
    },
  ];
  const journey = [
    {
      title: "背景资料",
      detail: data.currentBackground?.resume_name || "上传简历或手动填写",
      done: Boolean(data.currentBackground),
      href: "/profile",
    },
    {
      title: "申请项目",
      detail: data.currentApplication
        ? `${data.currentApplication.school_name} · ${data.currentApplication.program_name}`
        : "记录学校、专业与题目",
      done: Boolean(data.currentApplication),
      href: "/library",
    },
    {
      title: "故事访谈",
      detail: data.readyStories.length
        ? `${data.readyStories.length} 个故事可用于文书`
        : "提炼与项目相关的真实细节",
      done: data.readyStories.length > 0,
      href: "/library",
    },
    {
      title: "文书编辑",
      detail: data.currentEssay?.draft
        ? `${projectStatus(data.currentEssay)} · ${formatDate(data.currentEssay.updated_at)}`
        : "生成大纲、草稿并逐版修改",
      done: Boolean(data.currentEssay?.draft),
      href: data.currentEssay ? "/result" : "/library",
    },
  ];

  return (
    <main className="section dashboard-page">
      <div className="container dashboard-stack">
        <section className="dashboard-intro">
          <div className="dashboard-intro-copy">
            <p className="eyebrow">APPLICATION WORKSPACE</p>
            <h1>把申请文书，推进到下一步。</h1>
            <p>
              所有资料、项目、故事和草稿都围绕同一条申请链路组织，打开后先处理最需要继续的工作。
            </p>
          </div>
          <div className="dashboard-intro-actions">
            <Link href={data.nextAction.href} className="btn">
              <Icon name={data.nextAction.icon} size={18} />
              {data.nextAction.label}
            </Link>
            <Link href="/library" className="btn-secondary">
              查看全部申请
            </Link>
          </div>
        </section>

        {error ? (
          <div className="dashboard-error" role="alert">
            <div>
              <strong>工作区数据暂时无法加载</strong>
              <p>{error}</p>
            </div>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setLoading(true);
                setReloadKey((value) => value + 1);
              }}
            >
              重新加载
            </button>
          </div>
        ) : null}

        <section className="metric-grid" aria-label="申请工作区概览">
          {metrics.map((metric) => (
            <article className="metric-item" key={metric.label}>
              <span className="metric-icon">
                <Icon name={metric.icon} size={18} />
              </span>
              <div>
                <span>{metric.label}</span>
                <strong>{loading ? "—" : metric.value}</strong>
                <p>{loading ? "正在同步工作区" : metric.detail}</p>
              </div>
            </article>
          ))}
        </section>

        {!loading && !data.backgrounds.length ? (
          <section className="dashboard-empty">
            <span className="dashboard-empty-icon">
              <Icon name="compass" size={30} />
            </span>
            <div>
              <p className="eyebrow">START HERE</p>
              <h2>先建立一份可复用的背景资料</h2>
              <p>
                上传简历或手动填写经历。系统会以这份背景为起点，关联后续的学校项目、故事和文书。
              </p>
            </div>
            <Link href="/profile" className="btn">
              开始整理背景
              <Icon name="arrow-right" size={17} />
            </Link>
          </section>
        ) : (
          <div className="dashboard-main-grid">
            <section className="card current-work-card">
              <div className="dashboard-section-heading">
                <div>
                  <p className="eyebrow">CURRENT APPLICATION</p>
                  <h2>当前申请</h2>
                </div>
                {data.currentBackground ? (
                  <span className="status-pill status-pill-active">
                    进行中
                  </span>
                ) : null}
              </div>

              {data.currentBackground ? (
                <>
                  <div className="current-work-title">
                    <div>
                      <span>当前背景</span>
                      <h3>{data.currentBackground.resume_name}</h3>
                      <p>
                        {data.currentPerson?.display_name || "申请者"} ·{" "}
                        {
                          data.currentBackground.profile.basic_profile
                            .current_university
                        }{" "}
                        ·{" "}
                        {data.currentBackground.profile.basic_profile.major}
                      </p>
                    </div>
                    <span className="version-badge">
                      v{data.currentBackground.version}
                    </span>
                  </div>

                  <div className="journey-list">
                    {journey.map((item, index) => (
                      <Link
                        className={`journey-row ${
                          item.done ? "is-done" : ""
                        }`}
                        href={item.href}
                        key={item.title}
                      >
                        <span className="journey-state">
                          {item.done ? (
                            <Icon name="check" size={16} />
                          ) : (
                            index + 1
                          )}
                        </span>
                        <span className="journey-copy">
                          <strong>{item.title}</strong>
                          <small>{item.detail}</small>
                        </span>
                        <Icon name="arrow-right" size={17} />
                      </Link>
                    ))}
                  </div>

                  <div className="current-work-footer">
                    <p>
                      <Icon name="spark" size={17} />
                      {data.nextAction.label}
                    </p>
                    <Link className="btn" href={data.nextAction.href}>
                      {data.nextAction.label}
                      <Icon name="arrow-right" size={17} />
                    </Link>
                  </div>
                </>
              ) : (
                <div className="dashboard-inline-empty">
                  <p>建立背景资料后，这里会显示当前申请进度。</p>
                  <Link href="/profile" className="text-link">
                    前往背景资料
                  </Link>
                </div>
              )}
            </section>

            <aside className="card quick-actions-card">
              <div className="dashboard-section-heading">
                <div>
                  <p className="eyebrow">SHORTCUTS</p>
                  <h2>快速入口</h2>
                </div>
              </div>
              <Link href="/profile">
                <Icon name="user" size={19} />
                <span>
                  <strong>背景资料</strong>
                  <small>上传简历或补充经历</small>
                </span>
                <Icon name="arrow-right" size={16} />
              </Link>
              <Link href="/library">
                <Icon name="layers" size={19} />
                <span>
                  <strong>申请项目</strong>
                  <small>管理学校、故事与文书</small>
                </span>
                <Icon name="arrow-right" size={16} />
              </Link>
              <Link href="/program">
                <Icon name="target" size={19} />
                <span>
                  <strong>单项目分析</strong>
                  <small>快速分析一份项目要求</small>
                </span>
                <Icon name="arrow-right" size={16} />
              </Link>
              <Link href="/batch">
                <Icon name="folder" size={19} />
                <span>
                  <strong>批量生成</strong>
                  <small>一次处理多个申请方向</small>
                </span>
                <Icon name="arrow-right" size={16} />
              </Link>
            </aside>
          </div>
        )}

        <section className="card recent-projects-card">
          <div className="dashboard-section-heading">
            <div>
              <p className="eyebrow">RECENT PROJECTS</p>
              <h2>最近的申请项目</h2>
            </div>
            <Link href="/library" className="text-link">
              管理全部项目
            </Link>
          </div>
          {data.recentProjects.length ? (
            <div className="project-list">
              {data.recentProjects.map((project: ApplicationProject) => (
                <article key={project.id}>
                  <span className="project-monogram">
                    {project.school_name.slice(0, 1).toUpperCase()}
                  </span>
                  <div>
                    <strong>
                      {project.school_name} · {project.program_name}
                    </strong>
                    <p>
                      {project.story_count} 个故事 · {project.essay_count} 篇文书
                    </p>
                  </div>
                  <span className="project-date">
                    {formatDate(project.updated_at)}
                  </span>
                  <Link href="/library" aria-label="打开申请项目">
                    <Icon name="arrow-right" size={17} />
                  </Link>
                </article>
              ))}
            </div>
          ) : (
            <div className="dashboard-inline-empty">
              <p>还没有申请项目。建立背景资料后即可添加学校和专业。</p>
              <Link href="/library" className="text-link">
                打开申请项目
              </Link>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
