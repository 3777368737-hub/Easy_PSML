"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Icon from "@/components/icon";
import { apiBlobFetch, apiFetch, readableError } from "@/lib/api";
import { loadState, saveState, STORAGE_KEYS } from "@/lib/storage";
import type {
  ApplicationProject,
  BackgroundInstance,
  BatchResponse,
  BatchTone,
  EssayProject,
  EssayType,
  PersonSummary,
  ProfileResponse,
  StoryInstance,
  WorkspaceSnapshot,
} from "@/lib/types";

const ESSAY_TYPES: EssayType[] = [
  "Personal Statement",
  "Motivation Letter",
];

type AssemblyProjectNode = {
  projectId: string;
  storyIds: string[];
};

type AssemblyRoot = {
  backgroundId: string;
  projects: AssemblyProjectNode[];
};

type BranchConfig = {
  enabled: boolean;
  word_limit: string;
  prompt_text: string;
  tone: BatchTone;
  revision_instruction: string;
};

type DragPayload =
  | { type: "background"; id: string }
  | { type: "application-project"; id: string }
  | { type: "story"; id: string };

const initialProject = {
  school_name: "",
  program_name: "",
  program_details: "",
};

function branchKey(projectId: string, type: EssayType): string {
  return `${projectId}:${type}`;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    interviewing: "访谈中",
    ready: "可装配",
    extracted: "已提取",
    created: "待分析",
    analyzed: "已分析",
    outlined: "已有大纲",
    drafted: "已有草稿",
    reviewed: "已审核",
    stale: "需重生成",
  };
  return labels[status] || status;
}

function essayShort(type: EssayType): string {
  return type === "Personal Statement" ? "PS" : "ML";
}

function defaultBranch(type: EssayType): BranchConfig {
  return {
    enabled: type === "Personal Statement",
    word_limit: type === "Personal Statement" ? "800" : "500",
    prompt_text: "",
    tone: "balanced",
    revision_instruction: "",
  };
}

export default function WorkbenchPage() {
  const router = useRouter();
  const [workspace, setWorkspace] = useState<WorkspaceSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [personName, setPersonName] = useState("");
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [resumeName, setResumeName] = useState("科研简历");
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [selectedBackgroundId, setSelectedBackgroundId] = useState("");
  const [projectForm, setProjectForm] = useState(initialProject);
  const [selectedApplicationProjectId, setSelectedApplicationProjectId] =
    useState("");
  const [storyTitle, setStoryTitle] = useState("科研故事");
  const [storyFocus, setStoryFocus] = useState("");
  const [selectedStoryId, setSelectedStoryId] = useState("");
  const [storyReply, setStoryReply] = useState("");
  const [assemblyRoot, setAssemblyRoot] = useState<AssemblyRoot | null>(null);
  const [branchConfigs, setBranchConfigs] = useState<
    Record<string, BranchConfig>
  >({});
  const [dropActive, setDropActive] = useState("");

  const persons = useMemo(() => workspace?.persons || [], [workspace]);
  const backgrounds = useMemo(() => workspace?.backgrounds || [], [workspace]);
  const applicationProjects = useMemo(
    () => workspace?.application_projects || [],
    [workspace],
  );
  const stories = useMemo(() => workspace?.stories || [], [workspace]);
  const essayProjects = useMemo(() => workspace?.projects || [], [workspace]);

  const rootBackground = backgrounds.find(
    (item) => item.id === assemblyRoot?.backgroundId,
  );
  const selectedStory = stories.find((item) => item.id === selectedStoryId);

  const compatibleProjects = applicationProjects.filter(
    (project) =>
      assemblyRoot?.backgroundId === project.background_instance_id,
  );

  async function reloadWorkspace() {
    const next = await apiFetch<WorkspaceSnapshot>("/api/workspace");
    setWorkspace(next);
    return next;
  }

  function hydrateSelections(next: WorkspaceSnapshot) {
    const activePerson =
      loadState<string>(STORAGE_KEYS.activePersonId) || "";
    const activeBackground =
      loadState<string>(STORAGE_KEYS.activeBackgroundId) || "";
    const activeApplicationProject =
      loadState<string>(STORAGE_KEYS.activeApplicationProjectId) || "";
    const activeStory = loadState<string>(STORAGE_KEYS.activeStoryId) || "";
    const person =
      next.persons.find((item) => item.id === activePerson) ||
      next.persons[0];
    const background =
      next.backgrounds.find((item) => item.id === activeBackground) ||
      next.backgrounds[0];
    const applicationProject =
      next.application_projects.find(
        (item) => item.id === activeApplicationProject,
      ) ||
      next.application_projects.find(
        (item) => item.background_instance_id === background?.id,
      );
    const story =
      next.stories.find((item) => item.id === activeStory) ||
      next.stories[0];
    setSelectedPersonId(person?.id || "");
    setSelectedBackgroundId(background?.id || "");
    setSelectedApplicationProjectId(applicationProject?.id || "");
    setSelectedStoryId(story?.id || "");
    if (background) {
      setAssemblyRoot((current) =>
        current
          ? {
              ...current,
              backgroundId:
                next.backgrounds.some(
                  (item) => item.id === current.backgroundId,
                )
                  ? current.backgroundId
                  : background.id,
            }
          : { backgroundId: background.id, projects: [] },
      );
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        const next = await reloadWorkspace();
        hydrateSelections(next);
      } catch (err) {
        setError(readableError(err, "加载装配工作台失败"));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    const refresh = () => {
      void reloadWorkspace()
        .then(hydrateSelections)
        .catch((err) =>
          setError(readableError(err, "刷新装配工作台失败")),
        );
    };
    window.addEventListener("gradpilot:workspace-changed", refresh);
    return () =>
      window.removeEventListener("gradpilot:workspace-changed", refresh);
  }, []);

  function configFor(projectId: string, type: EssayType): BranchConfig {
    const existing = essayProjects.find(
      (project) =>
        project.application_project_id === projectId &&
        project.program.essay_type === type,
    );
    return (
      branchConfigs[branchKey(projectId, type)] || {
        ...defaultBranch(type),
        enabled: Boolean(existing),
        word_limit: String(
          existing?.program.word_limit || defaultBranch(type).word_limit,
        ),
        prompt_text: existing?.program.prompt_text || "",
        tone:
          (existing?.versions.find((item) => item.artifact_type === "draft")
            ?.metadata.tone as BatchTone | undefined) || "balanced",
      }
    );
  }

  function updateConfig(
    projectId: string,
    type: EssayType,
    changes: Partial<BranchConfig>,
  ) {
    setBranchConfigs((current) => ({
      ...current,
      [branchKey(projectId, type)]: {
        ...configFor(projectId, type),
        ...changes,
      },
    }));
  }

  async function createPerson() {
    if (!personName.trim()) return;
    setBusy("person");
    setError("");
    try {
      const person = await apiFetch<PersonSummary>("/api/persons", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: personName.trim() }),
      });
      setPersonName("");
      setSelectedPersonId(person.id);
      saveState(STORAGE_KEYS.activePersonId, person.id);
      await reloadWorkspace();
      setNotice(`已创建人物：${person.display_name}`);
    } catch (err) {
      setError(readableError(err, "创建人物失败"));
    } finally {
      setBusy("");
    }
  }

  async function extractBackground() {
    const person = persons.find((item) => item.id === selectedPersonId);
    if (!person || !resumeName.trim() || !resumeFile) {
      setError("请选择人物、填写简历名称并选择文件。");
      return;
    }
    setBusy("background");
    setError("");
    try {
      const form = new FormData();
      form.append("full_name", person.display_name);
      form.append("person_id", person.id);
      form.append("resume_name", resumeName.trim());
      form.append("strict_profile", "false");
      form.append("resume_file", resumeFile);
      const result = await apiFetch<ProfileResponse>(
        "/api/profile/extract",
        { method: "POST", body: form },
      );
      if (result.background_instance_id) {
        setSelectedBackgroundId(result.background_instance_id);
        saveState(
          STORAGE_KEYS.activeBackgroundId,
          result.background_instance_id,
        );
      }
      setResumeFile(null);
      await reloadWorkspace();
      setNotice("人物背景已进入背景表。");
    } catch (err) {
      setError(readableError(err, "提取背景失败"));
    } finally {
      setBusy("");
    }
  }

  async function createApplicationProject() {
    if (!selectedBackgroundId) {
      setError("请先选择一份人物背景。");
      return;
    }
    if (!projectForm.school_name.trim() || !projectForm.program_name.trim()) {
      setError("请填写学校和项目名称。");
      return;
    }
    setBusy("application-project");
    setError("");
    try {
      const project = await apiFetch<ApplicationProject>(
        "/api/application-projects",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            background_instance_id: selectedBackgroundId,
            school_name: projectForm.school_name.trim(),
            program_name: projectForm.program_name.trim(),
            program_details: projectForm.program_details.trim(),
          }),
        },
      );
      setSelectedApplicationProjectId(project.id);
      saveState(STORAGE_KEYS.activeApplicationProjectId, project.id);
      setProjectForm(initialProject);
      await reloadWorkspace();
      setNotice("申请项目已进入项目表。");
    } catch (err) {
      setError(readableError(err, "创建申请项目失败"));
    } finally {
      setBusy("");
    }
  }

  async function createStory() {
    const project = applicationProjects.find(
      (item) => item.id === selectedApplicationProjectId,
    );
    if (!project || !storyTitle.trim()) {
      setError("请选择申请项目并填写故事名称。");
      return;
    }
    setBusy("story");
    setError("");
    try {
      const story = await apiFetch<StoryInstance>(
        "/api/story-instances/start",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            background_instance_id: project.background_instance_id,
            application_project_id: project.id,
            title: storyTitle.trim(),
            focus: storyFocus.trim(),
          }),
        },
      );
      setSelectedStoryId(story.id);
      saveState(STORAGE_KEYS.activeStoryId, story.id);
      await reloadWorkspace();
      setNotice("故事已绑定到申请项目，并进入故事表。");
    } catch (err) {
      setError(readableError(err, "开始故事挖掘失败"));
    } finally {
      setBusy("");
    }
  }

  async function replyStory() {
    if (!selectedStory || !storyReply.trim()) return;
    setBusy("story-reply");
    setError("");
    try {
      await apiFetch<StoryInstance>(
        `/api/story-instances/${selectedStory.id}/reply`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_message: storyReply.trim() }),
        },
      );
      setStoryReply("");
      await reloadWorkspace();
      setNotice("故事回答已保存。");
    } catch (err) {
      setError(readableError(err, "提交故事回答失败"));
    } finally {
      setBusy("");
    }
  }

  async function downloadResume(background: BackgroundInstance) {
    try {
      const blob = await apiBlobFetch(
        `/api/backgrounds/${background.id}/resume`,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download =
        background.source_filename || `${background.resume_name}.txt`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(readableError(err, "下载简历失败"));
    }
  }

  function startDrag(
    event: React.DragEvent,
    payload: DragPayload,
  ) {
    event.dataTransfer.setData(
      "application/x-gradpilot-node",
      JSON.stringify(payload),
    );
    event.dataTransfer.effectAllowed = "copy";
  }

  function readDrag(event: React.DragEvent): DragPayload | null {
    try {
      return JSON.parse(
        event.dataTransfer.getData("application/x-gradpilot-node"),
      ) as DragPayload;
    } catch {
      return null;
    }
  }

  function addProjectToAssembly(projectId: string) {
    if (!assemblyRoot) {
      setError("请先将一份人物背景拖到装配画布。");
      return;
    }
    const project = applicationProjects.find((item) => item.id === projectId);
    if (!project || project.background_instance_id !== assemblyRoot.backgroundId) {
      setError("申请项目与当前人物背景不匹配，不能装配。");
      return;
    }
    setAssemblyRoot((current) => {
      if (!current) return current;
      if (current.projects.some((item) => item.projectId === projectId)) {
        return current;
      }
      return {
        ...current,
        projects: [...current.projects, { projectId, storyIds: [] }],
      };
    });
  }

  function addStoryToProject(projectId: string, storyId: string) {
    const project = applicationProjects.find((item) => item.id === projectId);
    const story = stories.find((item) => item.id === storyId);
    if (!project || !story || !assemblyRoot) return;
    if (
      story.background_instance_id !== assemblyRoot.backgroundId ||
      story.application_project_id !== projectId
    ) {
      setError("故事必须属于当前背景和当前申请项目，不能跨链路装配。");
      return;
    }
    if (story.status !== "ready") {
      setError("只有完成三轮挖掘的故事才能装配生成文书。");
      return;
    }
    setAssemblyRoot((current) => {
      if (!current) return current;
      return {
        ...current,
        projects: current.projects.map((item) =>
          item.projectId === projectId
            ? {
                ...item,
                storyIds: item.storyIds.includes(storyId)
                  ? item.storyIds
                  : [...item.storyIds, storyId],
              }
            : item,
        ),
      };
    });
  }

  function dropOnBackground(event: React.DragEvent) {
    event.preventDefault();
    setDropActive("");
    const payload = readDrag(event);
    if (payload?.type !== "background") return;
    const background = backgrounds.find((item) => item.id === payload.id);
    if (!background) return;
    setAssemblyRoot({
      backgroundId: background.id,
      projects: [],
    });
    setSelectedBackgroundId(background.id);
    saveState(STORAGE_KEYS.activeBackgroundId, background.id);
  }

  function dropOnProject(event: React.DragEvent, projectId: string) {
    event.preventDefault();
    setDropActive("");
    const payload = readDrag(event);
    if (payload?.type === "story") {
      addStoryToProject(projectId, payload.id);
    } else if (payload?.type === "application-project") {
      addProjectToAssembly(payload.id);
    }
  }

  function dropOnProjectArea(event: React.DragEvent) {
    event.preventDefault();
    setDropActive("");
    const payload = readDrag(event);
    if (payload?.type === "application-project") {
      addProjectToAssembly(payload.id);
    }
  }

  async function ensureBranch(
    projectId: string,
    type: EssayType,
    node: AssemblyProjectNode,
  ): Promise<EssayProject> {
    const applicationProject = applicationProjects.find(
      (item) => item.id === projectId,
    );
    if (!applicationProject) {
      throw new Error("申请项目不存在");
    }
    const config = configFor(projectId, type);
    const wordLimit = Number(config.word_limit);
    if (
      !config.prompt_text.trim() ||
      config.prompt_text.trim().length < 10 ||
      !Number.isInteger(wordLimit) ||
      wordLimit < 100 ||
      wordLimit > 5000
    ) {
      throw new Error(`${essayShort(type)} 需要 10 字符以上题目和 100-5000 字数。`);
    }
    let branch = essayProjects.find(
      (project) =>
        project.application_project_id === projectId &&
        project.program.essay_type === type,
    );
    if (!branch) {
      branch = await apiFetch<EssayProject>(
        `/api/application-projects/${projectId}/essays`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            application_project_id: projectId,
            essay_type: type,
            word_limit: wordLimit,
            prompt_text: config.prompt_text.trim(),
            story_instance_ids: node.storyIds,
            tone: config.tone,
          }),
        },
      );
    } else {
      branch = await apiFetch<EssayProject>(
        `/api/essay-projects/${branch.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            word_limit: wordLimit,
            prompt_text: config.prompt_text.trim(),
            story_instance_ids: node.storyIds,
          }),
        },
      );
    }
    return branch;
  }

  async function generateSingle(
    projectId: string,
    type: EssayType,
    node: AssemblyProjectNode,
    options: { silent?: boolean } = {},
  ) {
    const key = `${projectId}-${type}`;
    if (!options.silent) setBusy(key);
    setError("");
    try {
      let branch = await ensureBranch(projectId, type, node);
      branch = await apiFetch<EssayProject>(
        `/api/essay-projects/${branch.id}/analyze`,
        { method: "POST" },
      );
      branch = await apiFetch<EssayProject>(
        `/api/essay-projects/${branch.id}/outline`,
        { method: "POST" },
      );
      const config = configFor(projectId, type);
      branch = await apiFetch<EssayProject>(
        `/api/essay-projects/${branch.id}/draft`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tone: config.tone,
            target_length: Number(config.word_limit),
            revision_instruction: config.revision_instruction.trim(),
          }),
        },
      );
      await reloadWorkspace();
      if (!options.silent) {
        setNotice(`${essayShort(type)} 已生成，可继续修改语气。`);
      }
      return branch;
    } catch (err) {
      setError(readableError(err, `${essayShort(type)} 生成失败`));
      return null;
    } finally {
      if (!options.silent) setBusy("");
    }
  }

  async function rewriteBranch(
    projectId: string,
    type: EssayType,
    node: AssemblyProjectNode,
  ) {
    const config = configFor(projectId, type);
    if (!config.revision_instruction.trim()) {
      setError("请填写语气或内容修改意见。");
      return;
    }
    const key = `rewrite-${projectId}-${type}`;
    setBusy(key);
    setError("");
    try {
      const branch = await ensureBranch(projectId, type, node);
      await apiFetch<EssayProject>(
        `/api/essay-projects/${branch.id}/draft`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tone: config.tone,
            target_length: Number(config.word_limit),
            revision_instruction: config.revision_instruction.trim(),
          }),
        },
      );
      updateConfig(projectId, type, { revision_instruction: "" });
      await reloadWorkspace();
      setNotice(`${essayShort(type)} 已按语气和意见重写。`);
    } catch (err) {
      setError(readableError(err, "重写文书失败"));
    } finally {
      setBusy("");
    }
  }

  async function generateAll() {
    if (!assemblyRoot) {
      setError("装配画布还是空的。");
      return;
    }
    const tasks = assemblyRoot.projects.flatMap((node) =>
      ESSAY_TYPES.filter(
        (type) => configFor(node.projectId, type).enabled,
      ).map((type) => ({ node, type })),
    );
    if (!tasks.length) {
      setError("请至少选择一个 PS 或 ML 分支。");
      return;
    }
    setBusy("all");
    setError("");
    try {
      const hasExistingBranches = tasks.some((task) =>
        essayProjects.some(
          (project) =>
            project.application_project_id === task.node.projectId &&
            project.program.essay_type === task.type,
        ),
      );
      if (!hasExistingBranches && assemblyRoot.backgroundId) {
        const directions = assemblyRoot.projects.map((node) => {
          const applicationProject = applicationProjects.find(
            (item) => item.id === node.projectId,
          );
          if (!applicationProject) {
            throw new Error("装配中存在失效的申请项目。");
          }
          const essays = ESSAY_TYPES.filter(
            (type) => configFor(node.projectId, type).enabled,
          ).map((type) => {
            const config = configFor(node.projectId, type);
            const wordLimit = Number(config.word_limit);
            if (
              config.prompt_text.trim().length < 10 ||
              !Number.isInteger(wordLimit) ||
              wordLimit < 100 ||
              wordLimit > 5000
            ) {
              throw new Error(
                `${applicationProject.program_name} 的 ${essayShort(type)} 要求不完整。`,
              );
            }
            return {
              essay_type: type,
              word_limit: wordLimit,
              prompt_text: config.prompt_text.trim(),
              tone: config.tone,
            };
          });
          if (!essays.length) {
            throw new Error(
              `${applicationProject.program_name} 没有选择 PS 或 ML。`,
            );
          }
          if (!node.storyIds.length) {
            throw new Error(
              `${applicationProject.program_name} 还没有拖入可装配故事。`,
            );
          }
          return {
            application_project_id: applicationProject.id,
            school_name: applicationProject.school_name,
            program_name: applicationProject.program_name,
            program_details: applicationProject.program_details,
            story_instance_ids: node.storyIds,
            essays,
          };
        });
        const batch = await apiFetch<BatchResponse>("/api/batches", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            background_instance_id: assemblyRoot.backgroundId,
            request_id: crypto.randomUUID(),
            tone: "balanced",
            directions,
          }),
        });
        saveState(STORAGE_KEYS.batchId, batch.id);
        router.push("/batch");
        return;
      }
      for (let index = 0; index < tasks.length; index += 1) {
        const task = tasks[index];
        setNotice(
          `正在生成 ${index + 1}/${tasks.length}：${essayShort(task.type)}`,
        );
        const result = await generateSingle(
          task.node.projectId,
          task.type,
          task.node,
          { silent: true },
        );
        if (!result) return;
      }
      setNotice(`已完成 ${tasks.length} 份文书。`);
    } finally {
      setBusy("");
    }
  }

  function removeProject(projectId: string) {
    setAssemblyRoot((current) =>
      current
        ? {
            ...current,
            projects: current.projects.filter(
              (item) => item.projectId !== projectId,
            ),
          }
        : current,
    );
  }

  function removeStory(projectId: string, storyId: string) {
    setAssemblyRoot((current) =>
      current
        ? {
            ...current,
            projects: current.projects.map((item) =>
              item.projectId === projectId
                ? {
                    ...item,
                    storyIds: item.storyIds.filter(
                      (id) => id !== storyId,
                    ),
                  }
                : item,
            ),
          }
        : current,
    );
  }

  if (loading) {
    return (
      <main className="section">
        <div className="container">
          <p className="busy-status" role="status">
            <span className="spinner" /> 正在加载装配工作台…
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="section">
      <div className="container workbench-stack">
        <section className="workbench-heading">
          <div>
            <div className="kicker">APPLICATION PROJECTS</div>
            <h1 className="section-title">申请项目与文书装配</h1>
            <p className="muted">
              先选择一份背景，再管理学校项目与故事，最后生成对应的 PS / ML。系统会校验素材归属，避免跨项目混用。
            </p>
          </div>
          <div className="actions">
            <button
              className="btn"
              type="button"
              disabled={Boolean(busy) || !assemblyRoot?.projects.length}
              onClick={() => void generateAll()}
            >
              {busy === "all" ? "正在生成全部…" : "一键生成全部文书"}
            </button>
          </div>
        </section>

        {error ? <p className="notice" role="alert">{error}</p> : null}
        {notice ? <p className="notice success" role="status">{notice}</p> : null}

        {!backgrounds.length ? (
          <section className="workbench-onboarding">
            <div>
              <p className="eyebrow">FIRST APPLICATION</p>
              <h2>从一份背景资料开始</h2>
              <p>
                背景是学校项目、故事和文书的共同来源。建立后，你可以在同一页完成项目绑定、故事访谈和文书生成。
              </p>
              <div className="workbench-onboarding-steps">
                <span>
                  <strong>01</strong> 建立背景
                </span>
                <span>
                  <strong>02</strong> 添加学校项目
                </span>
                <span>
                  <strong>03</strong> 生成文书
                </span>
              </div>
            </div>
            <Link className="btn" href="/profile">
              整理第一份背景
              <Icon name="arrow-right" size={17} />
            </Link>
          </section>
        ) : (
        <section className="workbench-source-grid">
          <article className="card workbench-source-table">
            <div className="workbench-table-title">
              <div>
                <span className="workbench-step">A</span>
                <h2>人物背景信息</h2>
              </div>
              <span className="badge">{backgrounds.length}</span>
            </div>
            <details>
              <summary>新建人物与简历背景</summary>
              <div className="field">
                <label htmlFor="workbench-person">人物</label>
                <div className="actions">
                  <select
                    id="workbench-person"
                    value={selectedPersonId}
                    onChange={(event) => {
                      setSelectedPersonId(event.target.value);
                      saveState(
                        STORAGE_KEYS.activePersonId,
                        event.target.value,
                      );
                    }}
                  >
                    <option value="">选择人物</option>
                    {persons.map((person) => (
                      <option key={person.id} value={person.id}>
                        {person.display_name}
                      </option>
                    ))}
                  </select>
                  <input
                    aria-label="新人物姓名"
                    value={personName}
                    onChange={(event) => setPersonName(event.target.value)}
                    placeholder="新人物姓名"
                  />
                  <button
                    className="btn-secondary"
                    type="button"
                    disabled={busy === "person" || !personName.trim()}
                    onClick={() => void createPerson()}
                  >
                    新增人物
                  </button>
                </div>
              </div>
              <div className="field">
                <label htmlFor="workbench-resume-name">简历名称</label>
                <input
                  id="workbench-resume-name"
                  value={resumeName}
                  onChange={(event) => setResumeName(event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="workbench-resume-file">简历文件</label>
                <input
                  id="workbench-resume-file"
                  type="file"
                  accept=".txt,.md,.pdf,.docx"
                  onChange={(event) =>
                    setResumeFile(event.target.files?.[0] || null)
                  }
                />
              </div>
              <button
                className="btn-secondary"
                type="button"
                disabled={busy === "background" || !resumeFile}
                onClick={() => void extractBackground()}
              >
                提取到背景表
              </button>
            </details>
            <div className="workbench-table-list">
              {backgrounds.map((background) => {
                const person = persons.find(
                  (item) => item.id === background.person_id,
                );
                return (
                  <div
                    key={background.id}
                    className="workbench-source-item"
                    draggable
                    onDragStart={(event) =>
                      startDrag(event, {
                        type: "background",
                        id: background.id,
                      })
                    }
                    onDoubleClick={() => {
                      setAssemblyRoot({
                        backgroundId: background.id,
                        projects: [],
                      });
                      setSelectedBackgroundId(background.id);
                    }}
                  >
                    <span className="drag-grip">⋮⋮</span>
                    <div>
                      <strong>{background.resume_name}</strong>
                      <p>
                        {person?.display_name || "未知人物"} ·{" "}
                        {background.profile.basic_profile.major} · v
                        {background.version}
                      </p>
                    </div>
                    <div className="workbench-inline-actions">
                      <button
                        type="button"
                        onClick={() => {
                          saveState(
                            STORAGE_KEYS.activePersonId,
                            background.person_id,
                          );
                          saveState(
                            STORAGE_KEYS.activeBackgroundId,
                            background.id,
                          );
                          router.push("/profile");
                        }}
                      >
                        编辑
                      </button>
                      {background.source_filename ? (
                        <button
                          type="button"
                          onClick={() => void downloadResume(background)}
                        >
                          原简历
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="card workbench-source-table">
            <div className="workbench-table-title">
              <div>
                <span className="workbench-step">B</span>
                <h2>已记录项目</h2>
              </div>
              <span className="badge">{applicationProjects.length}</span>
            </div>
            <details>
              <summary>记录学校和专业项目</summary>
              <div className="field">
                <label htmlFor="workbench-background">绑定背景</label>
                <select
                  id="workbench-background"
                  value={selectedBackgroundId}
                  onChange={(event) =>
                    setSelectedBackgroundId(event.target.value)
                  }
                >
                  <option value="">选择背景</option>
                  {backgrounds.map((background) => (
                    <option key={background.id} value={background.id}>
                      {background.resume_name} ·{" "}
                      {background.profile.basic_profile.full_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid-2">
                <div className="field">
                  <label htmlFor="workbench-school">学校</label>
                  <input
                    id="workbench-school"
                    value={projectForm.school_name}
                    onChange={(event) =>
                      setProjectForm((current) => ({
                        ...current,
                        school_name: event.target.value,
                      }))
                    }
                  />
                </div>
                <div className="field">
                  <label htmlFor="workbench-program">专业 / 项目</label>
                  <input
                    id="workbench-program"
                    value={projectForm.program_name}
                    onChange={(event) =>
                      setProjectForm((current) => ({
                        ...current,
                        program_name: event.target.value,
                      }))
                    }
                  />
                </div>
              </div>
              <div className="field">
                <label htmlFor="workbench-details">项目资料</label>
                <textarea
                  id="workbench-details"
                  value={projectForm.program_details}
                  onChange={(event) =>
                    setProjectForm((current) => ({
                      ...current,
                      program_details: event.target.value,
                    }))
                  }
                />
              </div>
              <button
                className="btn-secondary"
                type="button"
                disabled={busy === "application-project"}
                onClick={() => void createApplicationProject()}
              >
                记录到项目表
              </button>
            </details>
            <div className="workbench-table-list">
              {applicationProjects.map((project) => {
                const background = backgrounds.find(
                  (item) =>
                    item.id === project.background_instance_id,
                );
                return (
                  <div
                    key={project.id}
                    className="workbench-source-item"
                    draggable
                    onDragStart={(event) =>
                      startDrag(event, {
                        type: "application-project",
                        id: project.id,
                      })
                    }
                    onDoubleClick={() =>
                      addProjectToAssembly(project.id)
                    }
                  >
                    <span className="drag-grip">⋮⋮</span>
                    <div>
                      <strong>
                        {project.school_name} · {project.program_name}
                      </strong>
                      <p>
                        {background?.resume_name || "未命名背景"} ·{" "}
                        {project.story_count} 故事 · {project.essay_count} 文书
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="card workbench-source-table">
            <div className="workbench-table-title">
              <div>
                <span className="workbench-step">C</span>
                <h2>已挖掘故事</h2>
              </div>
              <span className="badge">{stories.length}</span>
            </div>
            <details>
              <summary>挖掘并绑定到申请项目</summary>
              <div className="field">
                <label htmlFor="workbench-story-project">申请项目</label>
                <select
                  id="workbench-story-project"
                  value={selectedApplicationProjectId}
                  onChange={(event) => {
                    setSelectedApplicationProjectId(event.target.value);
                    saveState(
                      STORAGE_KEYS.activeApplicationProjectId,
                      event.target.value,
                    );
                  }}
                >
                  <option value="">选择项目</option>
                  {applicationProjects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.school_name} · {project.program_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="workbench-story-title">故事名称</label>
                <input
                  id="workbench-story-title"
                  value={storyTitle}
                  onChange={(event) => setStoryTitle(event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="workbench-story-focus">挖掘重点</label>
                <input
                  id="workbench-story-focus"
                  value={storyFocus}
                  onChange={(event) => setStoryFocus(event.target.value)}
                  placeholder="例如：科研能力、领导力、跨专业动机"
                />
              </div>
              <button
                className="btn-secondary"
                type="button"
                disabled={busy === "story"}
                onClick={() => void createStory()}
              >
                开始并绑定故事
              </button>
            </details>
            <div className="workbench-table-list">
              {stories.map((story) => {
                const project = applicationProjects.find(
                  (item) => item.id === story.application_project_id,
                );
                return (
                  <div
                    key={story.id}
                    className={`workbench-source-item ${
                      story.status === "ready" ? "is-ready" : ""
                    }`}
                    draggable={story.status === "ready" && Boolean(project)}
                    onDragStart={(event) =>
                      startDrag(event, { type: "story", id: story.id })
                    }
                    onClick={() => setSelectedStoryId(story.id)}
                  >
                    <span className="drag-grip">
                      {story.status === "ready" ? "⋮⋮" : "·"}
                    </span>
                    <div>
                      <strong>{story.title}</strong>
                      <p>
                        {project
                          ? `${project.school_name} · ${project.program_name}`
                          : "未绑定申请项目"}{" "}
                        · {statusLabel(story.status)} · 第 {story.round_no}/3 轮
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
            {selectedStory?.status === "interviewing" ? (
              <div className="workbench-story-reply">
                <strong>{selectedStory.title}</strong>
                {selectedStory.messages.slice(-1).map((message, index) => (
                  <p key={`${message.role}-${index}`}>{message.content}</p>
                ))}
                <textarea
                  value={storyReply}
                  onChange={(event) => setStoryReply(event.target.value)}
                  placeholder="回答当前故事问题"
                  maxLength={4000}
                />
                <button
                  className="btn-secondary"
                  type="button"
                  disabled={busy === "story-reply" || !storyReply.trim()}
                  onClick={() => void replyStory()}
                >
                  提交本轮回答
                </button>
              </div>
            ) : null}
          </article>
        </section>
        )}

        <section
          className={`card assembly-canvas ${
            dropActive === "background" ? "is-drop-active" : ""
          }`}
          onDragOver={(event) => {
            event.preventDefault();
            if (!assemblyRoot) setDropActive("background");
          }}
          onDragLeave={() => setDropActive("")}
          onDrop={dropOnBackground}
        >
          <div className="batch-heading">
            <div>
              <div className="kicker">PROJECT ASSEMBLY</div>
              <h2 className="section-title">当前项目的文书结构</h2>
              <p className="muted">
                选择背景后，关联学校项目与已完成故事，再为每个项目生成 PS 或 ML。
              </p>
            </div>
            {assemblyRoot ? (
              <button
                className="btn-secondary"
                type="button"
                onClick={() => setAssemblyRoot(null)}
              >
                清空画布
              </button>
            ) : null}
          </div>

          {!assemblyRoot || !rootBackground ? (
            <div className="assembly-empty">
              <strong>先选择一份人物背景</strong>
              <p>把左侧背景拖到这里，或双击已有背景条目。</p>
            </div>
          ) : (
            <div className="assembly-tree">
              <article className="assembly-root-node">
                <span className="assembly-node-label">人物背景</span>
                <h3>{rootBackground.resume_name}</h3>
                <p>
                  {
                    persons.find(
                      (item) => item.id === rootBackground.person_id,
                    )?.display_name
                  }{" "}
                  · {rootBackground.profile.basic_profile.major} ·{" "}
                  {rootBackground.profile.basic_profile.target_field}
                </p>
              </article>

              <div
                className={`assembly-project-drop ${
                  dropActive === "projects" ? "is-drop-active" : ""
                }`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDropActive("projects");
                }}
                onDragLeave={() => setDropActive("")}
                onDrop={dropOnProjectArea}
              >
                <span>
                  拖入与该背景匹配的申请项目
                  {compatibleProjects.length
                    ? `（可选 ${compatibleProjects.length} 个）`
                    : "（请先在项目表创建项目）"}
                </span>
              </div>

              <div className="assembly-project-list">
                {assemblyRoot.projects.map((node) => {
                  const project = applicationProjects.find(
                    (item) => item.id === node.projectId,
                  );
                  if (!project) return null;
                  const projectStories = stories.filter(
                    (story) =>
                      story.application_project_id === project.id &&
                      story.status === "ready",
                  );
                  return (
                    <article
                      className="assembly-project-node"
                      key={node.projectId}
                      onDragOver={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setDropActive(`project-${project.id}`);
                      }}
                      onDragLeave={() => setDropActive("")}
                      onDrop={(event) =>
                        dropOnProject(event, project.id)
                      }
                    >
                      <div className="assembly-project-heading">
                        <div>
                          <span className="assembly-node-label">
                            申请项目
                          </span>
                          <h3>
                            {project.school_name} · {project.program_name}
                          </h3>
                        </div>
                        <button
                          type="button"
                          className="workbench-remove"
                          onClick={() => removeProject(project.id)}
                        >
                          移出画布
                        </button>
                      </div>

                      <div
                        className={`assembly-story-drop ${
                          dropActive === `project-${project.id}`
                            ? "is-drop-active"
                            : ""
                        }`}
                      >
                        {node.storyIds.length ? (
                          node.storyIds.map((storyId) => {
                            const story = stories.find(
                              (item) => item.id === storyId,
                            );
                            if (!story) return null;
                            return (
                              <span
                                className="assembly-story-chip"
                                key={story.id}
                              >
                                {story.title}
                                <button
                                  type="button"
                                  aria-label={`移除故事 ${story.title}`}
                                  onClick={() =>
                                    removeStory(project.id, story.id)
                                  }
                                >
                                  ×
                                </button>
                              </span>
                            );
                          })
                        ) : (
                          <span>
                            拖入该项目下已挖掘故事，可多选
                            {projectStories.length
                              ? `（可选 ${projectStories.length} 个）`
                              : "（还没有完成故事）"}
                          </span>
                        )}
                      </div>

                      <div className="assembly-branches">
                        {ESSAY_TYPES.map((type) => {
                          const config = configFor(project.id, type);
                          const branch = essayProjects.find(
                            (item) =>
                              item.application_project_id === project.id &&
                              item.program.essay_type === type,
                          );
                          const key = `${project.id}-${type}`;
                          return (
                            <div
                              className={`assembly-branch ${
                                config.enabled ? "is-enabled" : ""
                              }`}
                              key={type}
                            >
                              <label className="batch-checkbox">
                                <input
                                  type="checkbox"
                                  checked={config.enabled}
                                  onChange={(event) =>
                                    updateConfig(project.id, type, {
                                      enabled: event.target.checked,
                                    })
                                  }
                                />
                                生成 {essayShort(type)}
                                {branch
                                  ? ` · ${statusLabel(branch.status)}`
                                  : ""}
                              </label>
                              {config.enabled ? (
                                <>
                                  <div className="grid-2">
                                    <div className="field">
                                      <label
                                        htmlFor={`${key}-words`}
                                      >
                                        目标字数
                                      </label>
                                      <input
                                        id={`${key}-words`}
                                        type="number"
                                        min={100}
                                        max={5000}
                                        value={config.word_limit}
                                        onChange={(event) =>
                                          updateConfig(
                                            project.id,
                                            type,
                                            {
                                              word_limit:
                                                event.target.value,
                                            },
                                          )
                                        }
                                      />
                                    </div>
                                    <div className="field">
                                      <label htmlFor={`${key}-tone`}>
                                        语气
                                      </label>
                                      <select
                                        id={`${key}-tone`}
                                        value={config.tone}
                                        onChange={(event) =>
                                          updateConfig(
                                            project.id,
                                            type,
                                            {
                                              tone: event.target
                                                .value as BatchTone,
                                            },
                                          )
                                        }
                                      >
                                        <option value="balanced">
                                          均衡自然
                                        </option>
                                        <option value="authentic">
                                          真实个人化
                                        </option>
                                        <option value="academic">
                                          学术严谨
                                        </option>
                                        <option value="concise">
                                          简洁直接
                                        </option>
                                      </select>
                                    </div>
                                  </div>
                                  <div className="field">
                                    <label htmlFor={`${key}-prompt`}>
                                      {essayShort(type)} 题目 / 要求
                                    </label>
                                    <textarea
                                      id={`${key}-prompt`}
                                      value={config.prompt_text}
                                      onChange={(event) =>
                                        updateConfig(
                                          project.id,
                                          type,
                                          {
                                            prompt_text:
                                              event.target.value,
                                          },
                                        )
                                      }
                                      placeholder="填写至少 10 个字符的题目或具体要求。"
                                    />
                                  </div>
                                  <div className="actions">
                                    <button
                                      className="btn"
                                      type="button"
                                      disabled={
                                        Boolean(busy) ||
                                        !node.storyIds.length
                                      }
                                      onClick={() =>
                                        void generateSingle(
                                          project.id,
                                          type,
                                          node,
                                        )
                                      }
                                    >
                                      {busy === key
                                        ? "生成中…"
                                        : branch
                                          ? `重新生成 ${essayShort(type)}`
                                          : `生成 ${essayShort(type)}`}
                                    </button>
                                    {branch?.draft ? (
                                      <button
                                        className="btn-secondary"
                                        type="button"
                                        onClick={() => {
                                          saveState(
                                            STORAGE_KEYS.activeProjectId,
                                            branch.id,
                                          );
                                          router.push("/result");
                                        }}
                                      >
                                        打开完整文稿
                                      </button>
                                    ) : null}
                                  </div>
                                  {branch?.draft ? (
                                    <>
                                      <div className="field">
                                        <label htmlFor={`${key}-revision`}>
                                          语气 / 内容修正意见
                                        </label>
                                        <textarea
                                          id={`${key}-revision`}
                                          value={
                                            config.revision_instruction
                                          }
                                          onChange={(event) =>
                                            updateConfig(
                                              project.id,
                                              type,
                                              {
                                                revision_instruction:
                                                  event.target.value,
                                              },
                                            )
                                          }
                                          placeholder="例如：更真诚一些，加强项目匹配，压缩第二段。"
                                        />
                                      </div>
                                      <button
                                        className="btn-secondary"
                                        type="button"
                                        disabled={
                                          busy ===
                                            `rewrite-${project.id}-${type}` ||
                                          !config
                                            .revision_instruction
                                            .trim()
                                        }
                                        onClick={() =>
                                          void rewriteBranch(
                                            project.id,
                                            type,
                                            node,
                                          )
                                        }
                                      >
                                        按意见重写
                                      </button>
                                      <p className="assembly-draft-preview">
                                        {branch.draft.slice(0, 260)}
                                        {branch.draft.length > 260 ? "…" : ""}
                                      </p>
                                    </>
                                  ) : null}
                                </>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
