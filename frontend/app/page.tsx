import Link from 'next/link';

const steps = [
  {
    id: '01',
    title: '背景采集',
    desc: '上传简历并自动回填核心信息',
  },
  {
    id: '02',
    title: '项目对齐',
    desc: '结合目标项目输出写作策略',
  },
  {
    id: '03',
    title: '故事挖掘',
    desc: '个性化追问提炼可写证据',
  },
  {
    id: '04',
    title: '文书生成',
    desc: '中文大纲 + 英文草稿并迭代',
  },
];

const highlights = ['简历解析自动回填', '引入个性化追问环节', '草稿可按意见重写'];

const features = [
  {
    icon: '01',
    title: '先分析项目，再搭叙事骨架',
    desc: '先完成背景结构化，再做项目匹配和故事提炼，避免“词很漂亮但逻辑空心”的文书问题。',
  },
  {
    icon: '02',
    title: '围绕你的目标追问',
    desc: '问题会围绕你的经历与项目要求动态展开，持续提炼“动机-行动-结果”的可写素材。',
  },
  {
    icon: '03',
    title: '多方向批量生成，逐篇继续打磨',
    desc: '一份个人背景可生成多个方向的 PS 和 ML，每篇保留中文大纲和英文草稿，支持下载与修改重写。',
  },
];

export default function HomePage() {
  return (
    <main className="landing">
      <div className="landing-glow landing-glow-a" />
      <div className="landing-glow landing-glow-b" />

      <section className="landing-hero">
        <div className="container landing-grid">
          <div className="landing-main">
            <p className="landing-kicker">GradPilot · DeepSeek 文书助手</p>
            <h1>
              <span className="hero-line">让你的经历脱颖而出</span>
              <span className="hero-break hero-line">写成打动招生官的申请文书</span>
            </h1>
            <div className="landing-highlights">
              {highlights.map((item) => (
                <span key={item} className="landing-tag">
                  {item}
                </span>
              ))}
            </div>
            <div className="landing-actions">
              <Link href="/profile" className="btn">
                立即开始
              </Link>
              <Link href="/batch" className="btn-secondary">多方向批量生成</Link>
            </div>
          </div>

          <div className="landing-panel">
            <p className="panel-title">产品流程预览</p>
            <div className="flow-grid">
              {steps.map((step) => (
                <article key={step.id} className="flow-card">
                  <span className="flow-id">{step.id}</span>
                  <h3>{step.title}</h3>
                  <p>{step.desc}</p>
                </article>
              ))}
            </div>
            <div className="panel-footer">
              <span className="panel-pill">输入：简历 + 目标项目</span>
              <span className="panel-pill">输出：中文大纲 + 英文草稿</span>
            </div>
          </div>
        </div>
      </section>

      <section className="section landing-features">
        <div className="container">
          <div className="landing-feature-head" id="why-gradpilot">
            <p className="landing-kicker">Why GradPilot</p>
            <h2 className="landing-section-title">为什么 GradPilot 不是普通 AI 文书生成器</h2>
          </div>
          <div className="feature-grid">
            {features.map((feature) => (
              <article key={feature.title} className="feature-card">
                <div className="feature-icon">{feature.icon}</div>
                <h3>{feature.title}</h3>
                <p>{feature.desc}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
