"use client";

import { useState, useEffect, useRef, useCallback } from "react";

/* ═══════════════════════════════════════════════════════════════
   DNA HELIX — Philosopher names & sentences as genetic code
   ═══════════════════════════════════════════════════════════════ */

const DNA_STRANDS: [string, string][] = [
  ["니체", "초인"],
  ["사실은 없다", "해석만 있을 뿐"],
  ["하이데거", "현존재"],
  ["언어는", "존재의 집"],
  ["칸트", "물자체"],
  ["사르트르", "자유"],
  ["타인은", "지옥이다"],
  ["플라톤", "이데아"],
  ["동굴 밖으로", "나가라"],
  ["쇼펜하우어", "의지"],
  ["데리다", "해체"],
  ["텍스트 밖은", "없다"],
  ["헤겔", "변증법"],
  ["올빼미는", "황혼에 난다"],
  ["후설", "현상학"],
  ["사태 그 자체로", "Epoché"],
  ["한병철", "수작업"],
  ["행복은", "손으로 완성된다"],
  ["소크라테스", "무지의 지"],
  ["파스칼", "생각하는 갈대"],
  ["카뮈", "부조리"],
  ["라캉", "무의식"],
  ["키르케고르", "불안"],
  ["비트겐슈타인", "언어의 한계"],
  ["스피노자", "에티카"],
  ["데카르트", "코기토"],
  ["기꺼이", "다시 한번"],
  ["신을 뺏었으니", "초인을 주겠다"],
  ["실존은", "본질에 선행"],
  ["인간은 만물의", "척도다"],
  ["나만의 색을", "만들어라"],
  ["권력의지", "Wille zur Macht"],
  ["영원회귀", "Da Capo"],
  ["과학은", "사유하지 않는다"],
  ["낙관주의는", "의무이다"],
  ["벤담", "공리주의"],
  ["롤스", "정의론"],
  ["하버마스", "공론장"],
  ["세상의 멱살을", "잡고 있는 내 손"],
  ["미래는", "열려 있다"],
];

interface Particle {
  y: number;
  offset: number;
  char: string;
  x: number;
  screenY: number;
  size: number;
  alpha: number;
}

function initDna(
  canvas: HTMLCanvasElement | null,
  densityMultiplier: number,
  alignment: number
): (() => void) | undefined {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  let width = 0;
  let height = 0;
  let t = 0;
  let animId = 0;
  const particles: Particle[] = [];

  function resize() {
    width = canvas!.width = canvas!.parentElement?.clientWidth ?? window.innerWidth;
    height = canvas!.height = canvas!.parentElement?.clientHeight ?? window.innerHeight;
  }

  window.addEventListener("resize", resize);
  resize();

  const count = Math.floor(DNA_STRANDS.length * densityMultiplier);
  for (let i = 0; i < count; i++) {
    const pair = DNA_STRANDS[i % DNA_STRANDS.length];
    particles.push({ y: i, offset: 0, char: pair[0], x: 0, screenY: 0, size: 12, alpha: 1 });
    particles.push({ y: i, offset: Math.PI, char: pair[1], x: 0, screenY: 0, size: 12, alpha: 1 });
  }

  function update(p: Particle, time: number) {
    const angle = p.y * 0.05 + time + p.offset;
    const radius = width < 768 ? 80 : 150;
    const x3d = Math.sin(angle) * radius;
    const z3d = Math.cos(angle) * radius;
    const fov = 1000;
    const scale = fov / (fov + z3d);
    p.x = width * alignment + x3d * scale;
    p.screenY = p.y * 15 * scale + height * 0.1;
    p.size = Math.max(7, 11 * scale);
    p.alpha = scale > 1 ? 1 : 0.25;
  }

  function animate() {
    ctx!.clearRect(0, 0, width, height);
    t += 0.008;
    ctx!.strokeStyle = "rgba(0,0,0,0.08)";
    ctx!.lineWidth = 1;

    for (let i = 0; i < particles.length; i += 2) {
      const p1 = particles[i];
      const p2 = particles[i + 1];
      update(p1, t);
      update(p2, t);

      ctx!.beginPath();
      ctx!.moveTo(p1.x, p1.screenY);
      ctx!.lineTo(p2.x, p2.screenY);
      ctx!.stroke();

      ctx!.font = `500 ${p1.size}px "Helvetica Neue", Helvetica, sans-serif`;
      ctx!.fillStyle = `rgba(0,0,0,${p1.alpha})`;
      ctx!.textAlign = "center";
      ctx!.fillText(p1.char, p1.x, p1.screenY);

      ctx!.font = `500 ${p2.size}px "Helvetica Neue", Helvetica, sans-serif`;
      ctx!.fillStyle = `rgba(0,0,0,${p2.alpha})`;
      ctx!.fillText(p2.char, p2.x, p2.screenY);
    }

    animId = requestAnimationFrame(animate);
  }

  animate();

  return () => {
    cancelAnimationFrame(animId);
    window.removeEventListener("resize", resize);
  };
}

/* ═══════════════════════════════════════════════════════════════
   DATA
   ═══════════════════════════════════════════════════════════════ */

const VOICES: { text: string; who: string; src?: string }[] = [
  { text: "사실은 없다, 오직 해석만 있을 뿐이다.", who: "NIETZSCHE", src: "ES GIBT KEINE TATSACHEN, NUR INTERPRETATIONEN" },
  { text: "언어는 존재의 집이다.", who: "HEIDEGGER", src: "DIE SPRACHE IST DAS HAUS DES SEINS" },
  { text: "나는 생각한다, 고로 존재한다.", who: "DESCARTES", src: "COGITO, ERGO SUM" },
  { text: "인간은 자유를 선고받았다.", who: "SARTRE" },
  { text: "행복은 수작업이다.", who: "HAN BYUNG-CHUL", src: "GLÜCK IST HANDARBEIT" },
  { text: "삶은 고통과 권태 사이의 진자운동이다.", who: "SCHOPENHAUER" },
  { text: "미네르바의 올빼미는 황혼에 날개를 편다.", who: "HEGEL" },
  { text: "타인은 지옥이다.", who: "SARTRE" },
  { text: "사람은 생각하는 갈대다.", who: "PASCAL" },
  { text: "사태 그 자체로!", who: "HUSSERL", src: "ZU DEN SACHEN SELBST!" },
  { text: "동굴 밖으로 나가라.", who: "PLATO" },
  { text: "인간은 존재의 주인이 아니다. 인간은 존재의 목자이다.", who: "HEIDEGGER" },
  { text: "과학은 사유하지 않는다.", who: "HEIDEGGER", src: "WISSENSCHAFT DENKT NICHT" },
  { text: "텍스트 밖은 없다.", who: "DERRIDA" },
  { text: "기꺼이 다시 한번!", who: "NIETZSCHE", src: "DA CAPO!" },
  { text: "신을 뺏었으니, 초인을 주겠다.", who: "NIETZSCHE" },
  { text: "낙관주의는 도덕적 의무이다.", who: "KANT" },
  { text: "인간은 만물의 척도다.", who: "PROTAGORAS" },
  { text: "게임을 비판하거나 거부하는 자는 이미 게임 속으로 들어가 있다.", who: "BLANCHOT" },
  { text: "내가 존재하지 않는 곳에서 나는 생각하고, 생각하지 않는 곳에서 존재한다.", who: "LACAN" },
  { text: "세상을 부정하려다 보면, 결국 세상의 멱살을 잡고 있는 내 손을 발견한다.", who: "CHOI DONG-IN" },
  { text: "나만의 색을 만들어, 세상을 그 색으로 덮어버려라.", who: "CHOI DONG-IN" },
  { text: "미래는 열려 있다. 미래는 예정되어 있지 않다.", who: "POPPER" },
  { text: "죽는 날까지 하늘을 우러러 한 점 부끄럼이 없기를.", who: "YUN DONG-JU" },
  { text: "모든 학문은 심리학에 봉사하게 될 것이다.", who: "NIETZSCHE" },
  { text: "사유는 수작업이다.", who: "HEIDEGGER", src: "GEDANKEN SIND HANDARBEIT" },
  { text: "진리를 여자라고 가정한다면?", who: "NIETZSCHE" },
  { text: "짧게 쓸 시간이 없어서 길게 쓰는 것을 용서하라.", who: "PASCAL" },
  { text: "산에서는 가장 짧은 길이 봉우리에서 봉우리로 가는 길이다. 그러나 그러기 위해서는 긴 다리를 가져야만 한다.", who: "NIETZSCHE" },
  { text: "모든 악은 불충분한 지식에서 비롯된다.", who: "DEUTSCH" },
  { text: "행복은 손을 통해서 들어온다. 행복은 손으로 완성된다.", who: "HAN BYUNG-CHUL" },
  { text: "나를 대상화시키며 나의 자유를 제한하는 타인은 내게 지옥이다.", who: "SARTRE" },
  { text: "신은 문법이 있다면 존재한다.", who: "NIETZSCHE" },
];

const ARCHITECTS = [
  "니체 NIETZSCHE", "하이데거 HEIDEGGER", "칸트 KANT", "한병철 HAN",
  "사르트르 SARTRE", "플라톤 PLATO", "쇼펜하우어 SCHOPENHAUER", "데리다 DERRIDA",
  "헤겔 HEGEL", "후설 HUSSERL", "소크라테스 SOCRATES", "아리스토텔레스 ARISTOTLE",
  "데카르트 DESCARTES", "스피노자 SPINOZA", "파스칼 PASCAL", "키르케고르 KIERKEGAARD",
  "라캉 LACAN", "카뮈 CAMUS", "비트겐슈타인 WITTGENSTEIN", "벤담 BENTHAM",
  "롤스 RAWLS", "하버마스 HABERMAS", "에피쿠로스 EPICURUS", "칼 포퍼 POPPER",
];

/* ═══════════════════════════════════════════════════════════════
   STYLES — Faithful to the SGL design
   ═══════════════════════════════════════════════════════════════ */

const S = {
  font: "'Helvetica Neue', Helvetica, Arial, sans-serif",

  landingView: (entered: boolean, hidden: boolean): React.CSSProperties => ({
    position: "fixed",
    top: 0,
    left: 0,
    width: "100%",
    height: "100%",
    zIndex: 100,
    background: "#fff",
    display: hidden ? "none" : "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    padding: "3rem",
    transition: "transform 1s cubic-bezier(0.85, 0, 0.15, 1)",
    transform: entered ? "translateY(-100%)" : "translateY(0)",
  }),

  landingCanvas: {
    position: "absolute" as const,
    top: 0,
    left: 0,
    width: "100%",
    height: "100%",
    zIndex: -1,
  },

  labView: (entered: boolean): React.CSSProperties => ({
    position: "absolute",
    top: 0,
    left: 0,
    width: "100%",
    height: "100%",
    overflowY: "auto",
    opacity: entered ? 1 : 0,
    visibility: entered ? "visible" : "hidden",
    transition: "opacity 1s ease",
  }),

  mainCanvas: {
    position: "fixed" as const,
    top: 0,
    right: 0,
    width: "50vw",
    height: "100vh",
    zIndex: 1,
    pointerEvents: "none" as const,
  },
} as const;

/* ═══════════════════════════════════════════════════════════════
   PAGE COMPONENT
   ═══════════════════════════════════════════════════════════════ */

export default function PhilosophyPage() {
  const [entered, setEntered] = useState(false);
  const [landingHidden, setLandingHidden] = useState(false);
  const landingCanvasRef = useRef<HTMLCanvasElement>(null);
  const mainCanvasRef = useRef<HTMLCanvasElement>(null);

  // Override body styles
  useEffect(() => {
    const prev = {
      overflow: document.body.style.overflow,
      background: document.body.style.background,
      color: document.body.style.color,
    };
    document.body.style.overflow = "hidden";
    document.body.style.background = "#ffffff";
    document.body.style.color = "#000000";
    return () => {
      document.body.style.overflow = prev.overflow;
      document.body.style.background = prev.background;
      document.body.style.color = prev.color;
    };
  }, []);

  // Init DNA animations
  useEffect(() => {
    const cleanupLanding = initDna(landingCanvasRef.current, 1.5, 0.5);
    const cleanupMain = initDna(mainCanvasRef.current, 1, 0.75);
    return () => {
      cleanupLanding?.();
      cleanupMain?.();
    };
  }, []);

  const enterLab = useCallback(() => {
    setEntered(true);
    setTimeout(() => setLandingHidden(true), 1000);
  }, []);

  return (
    <div
      style={{
        fontFamily: S.font,
        background: "#ffffff",
        color: "#000000",
        width: "100vw",
        height: "100vh",
        position: "relative",
      }}
    >
      {/* ════════════ LANDING VIEW ════════════ */}
      <section style={S.landingView(entered, landingHidden)}>
        <canvas ref={landingCanvasRef} style={S.landingCanvas} />

        {/* Nav */}
        <nav
          style={{
            display: "flex",
            justifyContent: "space-between",
            textTransform: "uppercase",
            fontSize: "0.8rem",
            letterSpacing: "0.1em",
            zIndex: 10,
          }}
        >
          <div>SPK // PROTOCOL 0.1</div>
          <div>STATUS: DECODING...</div>
          <div>EST. 2026</div>
        </nav>

        {/* Mission */}
        <div style={{ maxWidth: 600, zIndex: 10 }}>
          <h2
            style={{
              fontSize: "clamp(2.5rem, 6vw, 4rem)",
              lineHeight: 0.85,
              textTransform: "uppercase",
              fontWeight: 500,
              marginBottom: "2rem",
              letterSpacing: "-0.02em",
            }}
          >
            DECODING
            <br />
            THE DNA
            <br />
            OF STARTUPS
          </h2>
          <p
            style={{
              fontSize: "1.1rem",
              textTransform: "uppercase",
              maxWidth: "40ch",
              lineHeight: 1.4,
            }}
          >
            WE OPERATE AT THE INTERSECTION OF ANCIENT PHILOSOPHY AND MODERN
            ENTREPRENEURSHIP, ENGINEERING THE FOUNDATION OF MEANINGFUL VENTURES.
          </p>
        </div>

        {/* Enter */}
        <div style={{ display: "flex", justifyContent: "flex-end", zIndex: 10 }}>
          <button
            onClick={enterLab}
            style={{
              fontSize: "clamp(3rem, 8vw, 8vw)",
              textTransform: "uppercase",
              fontWeight: 500,
              lineHeight: 0.8,
              cursor: "pointer",
              border: "none",
              background: "none",
              textAlign: "right",
              fontFamily: S.font,
              color: "#000",
              transition: "opacity 0.3s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.5")}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
          >
            <span
              style={{
                display: "block",
                fontSize: "1rem",
                fontWeight: 400,
                marginBottom: "0.5rem",
              }}
            >
              ACCESS TERMINAL
            </span>
            ENTER LAB &mdash;
          </button>
        </div>
      </section>

      {/* ════════════ LAB VIEW ════════════ */}
      <section style={S.labView(entered)}>
        <canvas ref={mainCanvasRef} style={S.mainCanvas} />

        <main
          style={{
            padding: "2rem",
            maxWidth: 1600,
            margin: "0 auto",
            position: "relative",
          }}
        >
          {/* ── HERO ── */}
          <header style={{ marginBottom: "15vh", position: "relative" }}>
            <h1
              style={{
                fontSize: "clamp(4rem, 12vw, 12vw)",
                fontWeight: 500,
                lineHeight: 0.9,
                letterSpacing: "-0.04em",
                textTransform: "uppercase",
              }}
            >
              STAR
              <br />
              TUP
              <br />
              PHILO
              <br />
              SOPHY
              <br />
              LAB &mdash;
            </h1>
            <div
              style={{
                marginTop: "2rem",
                fontSize: "1.5rem",
                display: "flex",
                gap: "2rem",
                textTransform: "uppercase",
                flexWrap: "wrap",
              }}
            >
              <div>
                EST. 2026
                <br />
                SEOUL
              </div>
              <div>
                PHILOSOPHICAL DNA
                <br />
                &amp; STARTUP DESIGN
              </div>
            </div>
          </header>

          {/* ── VOICES FROM THE HELIX ── */}
          <section style={{ marginBottom: "10vh" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 2fr",
                gap: "4rem",
              }}
              className="offerings-grid"
            >
              <div
                style={{
                  fontSize: "3rem",
                  lineHeight: 0.9,
                  textTransform: "uppercase",
                  position: "sticky",
                  top: "2rem",
                  alignSelf: "start",
                }}
              >
                VOICES
                <br />
                FROM THE
                <br />
                HELIX
              </div>

              <div>
                {VOICES.map((v, i) => (
                  <div
                    key={i}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "50px 1fr",
                      marginBottom: "1.5rem",
                      borderBottom: "1px solid rgba(0,0,0,0.06)",
                      paddingBottom: "1.5rem",
                    }}
                  >
                    <span style={{ fontSize: "0.85rem", opacity: 0.3 }}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <p
                        style={{
                          fontSize: "1rem",
                          textTransform: "uppercase",
                          marginBottom: "0.3rem",
                          maxWidth: "50ch",
                        }}
                      >
                        &ldquo;{v.text}&rdquo;
                      </p>
                      <span
                        style={{
                          fontSize: "0.8rem",
                          opacity: 0.4,
                          letterSpacing: "0.1em",
                        }}
                      >
                        &mdash; {v.who}
                        {v.src && (
                          <span style={{ opacity: 0.5, marginLeft: "0.5rem" }}>
                            ({v.src})
                          </span>
                        )}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* ── ARCHITECTS ── */}
          <section style={{ marginBottom: "10vh" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 2fr",
                gap: "4rem",
              }}
              className="offerings-grid"
            >
              <div
                style={{
                  fontSize: "3rem",
                  lineHeight: 0.9,
                  textTransform: "uppercase",
                  position: "sticky",
                  top: "2rem",
                  alignSelf: "start",
                }}
              >
                THE
                <br />
                ARCHI
                <br />
                TECTS
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                  gap: "0",
                }}
              >
                {ARCHITECTS.map((a, i) => (
                  <div
                    key={a}
                    style={{
                      padding: "1rem 0",
                      borderBottom: "1px solid rgba(0,0,0,0.06)",
                      textTransform: "uppercase",
                      fontSize: "0.9rem",
                      display: "flex",
                      gap: "0.5rem",
                      alignItems: "baseline",
                    }}
                  >
                    <span style={{ fontSize: "0.7rem", opacity: 0.2 }}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    {a}
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* ── FOOTER ── */}
          <footer style={{ marginTop: "20vh", paddingBottom: "5rem" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "2rem",
              }}
              className="offerings-grid"
            >
              <div>
                <div
                  style={{
                    fontSize: "clamp(2rem, 5vw, 4rem)",
                    lineHeight: 0.8,
                    marginBottom: "2rem",
                    fontWeight: 500,
                    textTransform: "uppercase",
                  }}
                >
                  READY
                  <br />
                  TO
                  <br />
                  THINK?
                </div>
                <a
                  href="mailto:dongin@onlime.kr"
                  style={{
                    fontSize: "3rem",
                    textTransform: "uppercase",
                    textDecoration: "none",
                    color: "#000",
                    borderBottom: "3px solid transparent",
                    transition: "border-color 0.3s",
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.borderBottomColor = "#000")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.borderBottomColor = "transparent")
                  }
                >
                  JOIN NOW
                </a>
              </div>
              <div
                style={{
                  fontSize: "0.85rem",
                  textTransform: "uppercase",
                  maxWidth: "60ch",
                  lineHeight: 1.6,
                }}
              >
                스타트업 필러소피 모임. 서울. 철학하는 창업자들의 실험실.
                수천 년 인류 사유의 정수 위에서 사업을 설계하는 사람들.
                깊이 있는 뿌리와 중심을 먼저 만들어야 세상을 바꿀 수 있다.
                <br />
                <br />
                DONGIN@ONLIME.KR
                <br />
                ALL SESSIONS SUBJECT TO PHILOSOPHICAL RIGOR.
              </div>
            </div>
          </footer>
        </main>
      </section>

      {/* ── RESPONSIVE OVERRIDES ── */}
      <style>{`
        @media (max-width: 768px) {
          .offerings-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
