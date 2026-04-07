import { readFile, writeFile, rename, access } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";
import type { KakaoMessage } from "./types.js";

function todayDateStr(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function formatTime(): string {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

function formatMessages(
  messagesByChat: Record<string, KakaoMessage[]>
): string {
  const lines: string[] = [];

  for (const [chatName, messages] of Object.entries(messagesByChat)) {
    lines.push(`### ${chatName}`);
    for (const msg of messages) {
      lines.push(`- **${msg.time_raw}** ${msg.author}: ${msg.body}`);
    }
    lines.push("");
  }

  return lines.join("\n");
}

function createDailyNote(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  const prev = new Date(y, m - 1, d - 1);
  const next = new Date(y, m - 1, d + 1);
  const fmt = (dt: Date) =>
    `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;

  return `---
created: ${dateStr} ${formatTime()}
type: daily
author:
  - "[[🙍‍♂️최동인]]"
index:
  - "[[MOC Daily Notes]]"
---
#### [[${fmt(prev)} |◀︎]] ${dateStr} [[${fmt(next)} |▶︎]]
---
## ==잡서



---
## 리뷰


---
#### 생성
\`\`\`dataview
list
from ""
where file.cday = date(${dateStr}) AND !contains(file.folder, "3. Think/3.1 Daily")
\`\`\`
#### 변형
\`\`\`dataview
list
from ""
where file.mday = date(${dateStr}) AND !contains(file.folder, "3. Think/3.1 Daily") AND file.cday != date(${dateStr})
\`\`\`
`;
}

async function fileExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

export async function appendToDaily(
  messagesByChat: Record<string, KakaoMessage[]>,
  dailyNotePath: string
): Promise<void> {
  const dateStr = todayDateStr();
  const filePath = join(dailyNotePath, `${dateStr}.md`);

  let content: string;
  if (await fileExists(filePath)) {
    content = await readFile(filePath, "utf-8");
  } else {
    content = createDailyNote(dateStr);
    console.log(`[obsidian-writer] Created new daily note: ${dateStr}.md`);
  }

  const newContent = formatMessages(messagesByChat);
  const updateTime = `> _${formatTime()} 업데이트 by Onlime_\n\n`;

  if (content.includes("## 카카오톡")) {
    // Section exists - append before the next section (## 리뷰 or ---)
    const kakaoIdx = content.indexOf("## 카카오톡");
    // Find the end of the 카카오톡 section (next ## heading or --- separator)
    const afterKakao = content.slice(kakaoIdx + "## 카카오톡".length);
    const nextSectionMatch = afterKakao.match(/\n---\n|\n## /);

    if (nextSectionMatch && nextSectionMatch.index !== undefined) {
      const insertPos =
        kakaoIdx + "## 카카오톡".length + nextSectionMatch.index;
      content =
        content.slice(0, insertPos) +
        "\n" +
        newContent +
        content.slice(insertPos);
    } else {
      // No next section found, append at the end of the file
      content += "\n" + newContent;
    }
  } else {
    // Insert ## 카카오톡 section before ## 리뷰
    const reviewIdx = content.indexOf("## 리뷰");
    const kakaoSection = `## 카카오톡\n${updateTime}${newContent}\n`;

    if (reviewIdx !== -1) {
      // Find the --- before ## 리뷰
      const beforeReview = content.slice(0, reviewIdx);
      const lastDash = beforeReview.lastIndexOf("---");
      if (lastDash !== -1) {
        content =
          content.slice(0, lastDash) +
          kakaoSection +
          "---\n" +
          content.slice(reviewIdx);
      } else {
        content =
          content.slice(0, reviewIdx) + kakaoSection + content.slice(reviewIdx);
      }
    } else {
      // No ## 리뷰 found, append at end
      content += "\n" + kakaoSection;
    }
  }

  // Atomic write
  const tmpPath = join(
    tmpdir(),
    `onlime-${randomBytes(8).toString("hex")}.md`
  );
  await writeFile(tmpPath, content, "utf-8");
  await rename(tmpPath, filePath);

  const totalMsgs = Object.values(messagesByChat).reduce(
    (sum, msgs) => sum + msgs.length,
    0
  );
  console.log(
    `[obsidian-writer] Wrote ${totalMsgs} messages to ${dateStr}.md`
  );
}
