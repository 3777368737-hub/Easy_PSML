import Link from "next/link";
import Icon, { type IconName } from "@/components/icon";
const steps: {
  title: string;
  desc: string;
  detail: string;
  icon: IconName;
  href: string;
}[] = [
  {
    title: "整理你的背景",
    desc: "每一段经历，都有价值",
    detail: "上传简历或填写背景，整理你的学术、实践与项目经历。",
    icon: "user",
    href: "/profile",
  },
  {
    title: "理解目标项目",
    desc: "找到彼此契合的地方",
    detail: "结合项目要求，明确你的匹配优势与文书写作方向。",
    icon: "target",
    href: "/program",
  },
  {
    title: "挖掘真实故事",
    desc: "把经历讲得更具体",
    detail: "通过三轮引导式访谈，提炼行动、贡献与成长。",
    icon: "chat",
    href: "/story",
  },
  {
    title: "打磨申请文书",
    desc: "让故事成为清晰表达",
    detail: "查看中文大纲、生成英文草稿，并按反馈逐步修改。",
    icon: "file",
    href: "/result",
  },
];
export default function HomePage() {
  return (
    <main className="section home-page">
      <div className="container">
        <div className="home-heading">
          <div>
            <p className="eyebrow">A NEW CHAPTER STARTS HERE</p>
            <h1>下一程，从你的故事开始。</h1>
            <p className="muted">
              欢迎来到 GradPilot，你的研究生申请文书工作空间。
            </p>
          </div>
          <span className="badge">Personal Statement & Motivation Letter</span>
        </div>
        <section className="hero-banner" aria-labelledby="hero-title">
          <div className="hero-copy">
            <span className="hero-label">
              <Icon name="spark" size={16} /> 让经历被看见，让表达有方向
            </span>
            <h2 id="hero-title">
              你的经历，
              <br />
              值得被<span>好好讲述。</span>
            </h2>
            <p>
              从第一段经历到一篇完整草稿，
              <br />
              用清晰的步骤，写出真正属于你的申请故事。
            </p>
            <div className="actions">
              <Link href="/profile" className="btn light">
                开始整理背景
              </Link>
              <a href="#workflow" className="hero-link">
                了解写作流程
              </a>
            </div>
            <div className="hero-caption">
              <Icon name="check" size={16} /> 中文梳理思路 <span>·</span>{" "}
              英文呈现故事 <span>·</span> 持续修改完善
            </div>
          </div>
          <div
            className="essay-visual"
            aria-label="文书结构示意，非实际生成结果"
          >
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="paper-preview">
              <div className="paper-top">
                <span>YOUR NEXT CHAPTER</span>
                <Icon name="file" size={18} />
              </div>
              <h3>
                Personal
                <br />
                Statement<span className="paper-dot">.</span>
              </h3>
              <p className="paper-subtitle">A story only you can tell.</p>
              <div className="paper-rule" />
              <div className="paper-section">
                <span>MY MOTIVATION</span>
                <i />
                <i />
                <i className="short" />
              </div>
              <div className="paper-section">
                <span>EXPERIENCE & GROWTH</span>
                <i />
                <i />
                <i className="medium" />
              </div>
              <div className="paper-bottom">
                <span>从你的真实经历出发</span>
                <Icon name="compass" size={20} />
              </div>
            </div>
            <div className="floating-note">
              <span className="note-icon">
                <Icon name="spark" />
              </span>
              <div>
                <strong>让每段经历都有意义</strong>
                <small>动机 · 行动 · 结果 · 成长</small>
              </div>
            </div>
            <span className="preview-label">文书结构示意</span>
          </div>
        </section>
        <section id="workflow" className="workflow-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">YOUR APPLICATION JOURNEY</p>
              <h2>把复杂的申请，拆成四个清晰步骤</h2>
            </div>
            <span className="muted">按自己的节奏，逐步完成</span>
          </div>
          <div className="journey-grid">
            {steps.map((step, index) => (
              <Link className="journey-card" key={step.href} href={step.href}>
                <div className="journey-top">
                  <span className={`icon-tile tile-${index}`}>
                    <Icon name={step.icon} size={23} />
                  </span>
                  <span className="journey-number">0{index + 1}</span>
                </div>
                <h3>{step.title}</h3>
                <strong>{step.desc}</strong>
                <p>{step.detail}</p>
                <span className="journey-action">
                  {index === 0 ? "从这里开始" : "查看此步骤"}
                </span>
              </Link>
            ))}
          </div>
        </section>
        <section className="bottom-note">
          <span className="icon-tile">
            <Icon name="book" />
          </span>
          <div>
            <h3>准备好一份简历，以及一个想申请的项目。</h3>
            <p>也可以直接手动填写。AI 会帮你梳理，你始终决定如何讲述。</p>
          </div>
          <Link href="/profile" className="text-link">
            进入工作空间
          </Link>
        </section>
      </div>
    </main>
  );
}
