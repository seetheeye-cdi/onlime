import cron from "node-cron";
import { loadConfig } from "./config.js";
import { getDb } from "./db.js";
import { collectKakao } from "./collectors/kakao.js";
import { collectGmailMcp } from "./collectors/gmail-mcp.js";
import { collectGcalMcp } from "./collectors/gcal-mcp.js";
import { startPlaudWatcher, stopPlaudWatcher } from "./collectors/plaud.js";
import {
  startTelegramBot,
  stopTelegramBot,
  pushMorningBrief,
  pushDailySummary,
  pushAlert,
} from "./collectors/telegram-bot.js";
import { loadPeopleFromVault, loadProjectsFromVault } from "./people-loader.js";
import { generateDailySummary, generateContext } from "./ai/summarizer.js";
import { appendToDailySection } from "./writer.js";
import { notify, notifyError } from "./notify.js";

async function main() {
  console.log("[onlime] Starting Onlime v3 daemon...");

  // 1. DB 초기화
  getDb();
  console.log("[onlime] SQLite initialized");

  // 2. 설정 로드
  const config = await loadConfig();
  console.log(`[onlime] Vault: ${config.obsidianVaultPath}`);
  console.log(
    `[onlime] Poll: kakao=${config.pollIntervals.kakao}m, gmail=${config.pollIntervals.gmail}m, gcal=${config.pollIntervals.gcal}m`
  );

  // 3. People & Projects 로드
  const peopleCount = await loadPeopleFromVault();
  const projectCount = await loadProjectsFromVault();
  console.log(`[onlime] ${peopleCount} people, ${projectCount} projects`);

  // 4. Plaud 폴더 감시 시작
  await startPlaudWatcher(config);

  // 5. 텔레그램 봇 시작
  const telegramActive = await startTelegramBot();

  // 6. 초기 수집
  console.log("[onlime] Initial collection...");
  const results = await Promise.allSettled([
    collectKakao(config),
    collectGmailMcp(config),
    collectGcalMcp(config),
  ]);
  const counts = results.map((r) => (r.status === "fulfilled" ? r.value : 0));
  console.log(`[onlime] Initial: kakao=${counts[0]}, gmail=${counts[1]}, gcal=${counts[2]}`);

  // 7. 스케줄 등록

  // 카카오톡: N분마다
  cron.schedule(`*/${config.pollIntervals.kakao} * * * *`, async () => {
    try {
      await collectKakao(config);
    } catch (err) {
      console.error("[onlime] KakaoTalk:", err);
      await notifyError("Onlime", "카카오톡 수집 실패").catch(() => {});
      await pushAlert("카카오톡 수집 실패").catch(() => {});
    }
  });

  // Gmail: 1분 오프셋
  cron.schedule(`1-59/${config.pollIntervals.gmail} * * * *`, async () => {
    try {
      await collectGmailMcp(config);
    } catch (err) {
      console.error("[onlime] Gmail:", err);
      await pushAlert("Gmail 수집 실패").catch(() => {});
    }
  });

  // Google Calendar
  cron.schedule(`*/${config.pollIntervals.gcal} * * * *`, async () => {
    try {
      await collectGcalMcp(config);
    } catch (err) {
      console.error("[onlime] GCal:", err);
    }
  });

  // Morning Brief (08:00) → 텔레그램 푸시
  cron.schedule(`0 ${config.morningBriefHour} * * *`, async () => {
    console.log("[onlime] Morning brief...");
    try {
      await pushMorningBrief();
      await notify("Onlime", "모닝 브리프 전송 완료");
    } catch (err) {
      console.error("[onlime] Morning brief error:", err);
    }
  });

  // 일일 요약 (23:00) → Obsidian + 텔레그램
  cron.schedule(`0 ${config.summarizeHour} * * *`, async () => {
    console.log("[onlime] Daily summary...");
    try {
      const summary = await generateDailySummary();
      await appendToDailySection("리뷰", summary);
      await pushDailySummary();
      await notify("Onlime", "일일 요약 완료");
    } catch (err) {
      console.error("[onlime] Summary:", err);
      await notifyError("Onlime", "일일 요약 실패").catch(() => {});
    }
  });

  // 컨텍스트 생성 (22:30)
  cron.schedule("30 22 * * *", async () => {
    try {
      await generateContext();
    } catch (err) {
      console.error("[onlime] Context:", err);
    }
  });

  // Pre-Meeting Brief (30분마다)
  cron.schedule("*/30 * * * *", async () => {
    try {
      // 동적 import로 pre-meeting 스크립트 실행
      const { execFile } = await import("node:child_process");
      const { promisify } = await import("node:util");
      const exec = promisify(execFile);
      await exec("npx", ["tsx", "src/scripts/pre-meeting.ts"], {
        cwd: import.meta.dirname + "/..",
        timeout: 60_000,
        env: { ...process.env },
      });
    } catch {
      // 미팅 없으면 정상적으로 종료되므로 에러 무시
    }
  });

  const status = [
    `${peopleCount}명`,
    `${projectCount}PJ`,
    telegramActive ? "TG✅" : "TG❌",
  ].join(", ");

  await notify("Onlime", `시작됨 (${status})`);
  console.log(`[onlime] Daemon running (${status}). Ctrl+C to stop.`);

  // Graceful shutdown
  const shutdown = () => {
    console.log("\n[onlime] Shutting down...");
    stopPlaudWatcher();
    stopTelegramBot();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((err) => {
  console.error("[onlime] Fatal:", err);
  process.exit(1);
});
