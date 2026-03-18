import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFile, writeFile, rename } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";

const exec = promisify(execFile);

function todayDateStr(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function extractKakaoSection(content: string): string | null {
  const startIdx = content.indexOf("## 카카오톡");
  if (startIdx === -1) return null;

  const afterStart = content.slice(startIdx);
  // Find the end: next "---" separator or "## 리뷰"
  const endMatch = afterStart.match(/\n---\n|\n## 리뷰/);
  if (endMatch && endMatch.index !== undefined) {
    return afterStart.slice(0, endMatch.index);
  }
  return afterStart;
}

async function summarizeWithOpenClaw(kakaoContent: string): Promise<string> {
  const prompt = `다음은 오늘의 카카오톡 대화 기록입니다. 이것을 분석해서 아래 형식으로 요약해주세요:

1. 핵심 내용 요약 (채팅방별로 1-2줄)
2. 결정된 사항 (있는 경우)
3. 액션 아이템 (할 일 목록, 체크박스 형식)
4. 중요 연락처는 [[위키링크]] 형식으로 표시

카카오톡 기록:
${kakaoContent}

형식:
### 카카오톡 요약
(요약 내용)

### 액션 아이템
- [ ] (할 일)`;

  try {
    // Use openclaw CLI to get AI summary
    const { stdout } = await exec(
      "openclaw",
      ["run", "--prompt", prompt, "--no-interactive"],
      { timeout: 60_000 }
    );
    return stdout.trim();
  } catch {
    // Fallback: try using the openclaw gateway API
    try {
      const { stdout } = await exec(
        "curl",
        [
          "-s",
          "-X",
          "POST",
          "http://127.0.0.1:18789/api/chat",
          "-H",
          "Content-Type: application/json",
          "-d",
          JSON.stringify({ message: prompt }),
        ],
        { timeout: 60_000 }
      );
      const response = JSON.parse(stdout);
      return response.reply || response.message || stdout;
    } catch (err) {
      console.error("[summarizer] AI summarization failed:", err);
      return `### 카카오톡 요약\n> AI 요약 생성 실패. 원본 기록을 참고하세요.`;
    }
  }
}

export async function runDailySummary(dailyNotePath: string): Promise<void> {
  const dateStr = todayDateStr();
  const filePath = join(dailyNotePath, `${dateStr}.md`);

  let content: string;
  try {
    content = await readFile(filePath, "utf-8");
  } catch {
    console.log("[summarizer] No daily note found for today");
    return;
  }

  const kakaoContent = extractKakaoSection(content);
  if (!kakaoContent) {
    console.log("[summarizer] No KakaoTalk section found in today's note");
    return;
  }

  console.log("[summarizer] Generating AI summary...");
  const summary = await summarizeWithOpenClaw(kakaoContent);

  // Insert summary into ## 리뷰 section
  const reviewIdx = content.indexOf("## 리뷰");
  if (reviewIdx !== -1) {
    const afterReview = content.slice(reviewIdx + "## 리뷰".length);
    const nextSectionMatch = afterReview.match(/\n---\n|\n#### /);

    const summaryBlock = `\n\n${summary}\n`;

    if (nextSectionMatch && nextSectionMatch.index !== undefined) {
      const insertPos = reviewIdx + "## 리뷰".length + nextSectionMatch.index;
      content =
        content.slice(0, insertPos) + summaryBlock + content.slice(insertPos);
    } else {
      content =
        content.slice(0, reviewIdx + "## 리뷰".length) +
        summaryBlock +
        content.slice(reviewIdx + "## 리뷰".length);
    }
  } else {
    content += `\n## 리뷰\n\n${summary}\n`;
  }

  // Atomic write
  const tmpPath = join(
    tmpdir(),
    `onlime-summary-${randomBytes(8).toString("hex")}.md`
  );
  await writeFile(tmpPath, content, "utf-8");
  await rename(tmpPath, filePath);

  console.log(`[summarizer] Summary written to ${dateStr}.md`);
}

// Allow running standalone
if (process.argv[1]?.endsWith("summarizer.ts") || process.argv[1]?.endsWith("summarizer.js")) {
  const dailyNotePath =
    process.argv[2] || "/Users/aiparty/Desktop/Obsidian_sinc/2. OUTPUT/Daily";
  runDailySummary(dailyNotePath).catch(console.error);
}
