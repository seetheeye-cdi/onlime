/**
 * Gmail MCP Collector — claude -p로 이메일 수집
 *
 * googleapis OAuth 대신 이미 연결된 Claude Code MCP 서버 활용.
 * 설정 제로. claude -p 호출당 ~$0.03-0.05 토큰 비용.
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { v4 as uuid } from "uuid";
import type { OnlimeEvent, OnlimeConfig } from "../types.js";
import { getCursor, setCursor, insertEvent, eventExists } from "../db.js";
import { writeEventNote } from "../writer.js";
import { enrichEvent } from "../enricher.js";
import { notify } from "../notify.js";

const exec = promisify(execFile);

// 수집 제외 패턴
const SKIP_SENDERS = [/noreply/i, /no-reply/i, /feedback@slack/i, /security@/i, /mailer-daemon/i, /notifications?@/i];
const SKIP_SUBJECTS = [/보안\s*코드/i, /security\s*code/i, /로그인/i, /login/i, /인증번호/i, /verify/i];

interface McpEmail {
  id: string;
  subject: string;
  from: string;
  to: string;
  date: string;
  snippet: string;
  labels: string[];
}

async function fetchEmailsViaMcp(query: string, maxResults: number = 10): Promise<McpEmail[]> {
  try {
    const prompt = `Search Gmail with query: "${query}" (maxResults: ${maxResults}).
For each email found, output ONLY a JSON array with this exact format, no other text:
[{"id":"msg_id","subject":"subject","from":"sender","to":"recipient","date":"ISO date","snippet":"preview text","labels":["label1"]}]

If no emails found, output: []`;

    const { stdout } = await exec(
      "claude",
      [
        "-p", prompt,
        "--allowedTools", "mcp__claude_ai_Gmail__gmail_search_messages",
        "--output-format", "text",
      ],
      { timeout: 120_000, env: { ...process.env, LANG: "en_US.UTF-8" } }
    );

    // JSON 배열 추출 (claude 출력에서 JSON 부분만)
    const jsonMatch = stdout.match(/\[[\s\S]*\]/);
    if (!jsonMatch) {
      console.log("[gmail-mcp] No JSON in response");
      return [];
    }

    const parsed = JSON.parse(jsonMatch[0]);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    console.error("[gmail-mcp] claude -p failed:", err);
    return [];
  }
}

function shouldSkipEmail(from: string, subject: string, labels: string[]): boolean {
  if (SKIP_SENDERS.some(re => re.test(from))) return true;
  if (SKIP_SUBJECTS.some(re => re.test(subject))) return true;
  if (labels.some(l => /promotions|social/i.test(l))) return true;
  return false;
}

export async function collectGmailMcp(_config: OnlimeConfig): Promise<number> {
  let totalNew = 0;

  // 개인 메일 + 업무 메일 모두 수집
  // MCP는 현재 연결된 계정(cdiseetheeye@gmail.com) 기반
  // 업무 메일(seetheeye@chamchi.kr)도 같은 Gmail에 연동되어 있으면 자동 수집
  const queries = [
    "is:inbox newer_than:1h -category:promotions -category:social",
    "to:seetheeye@chamchi.kr newer_than:1h",
  ];

  for (const query of queries) {
    console.log(`[gmail-mcp] Fetching: ${query}`);
    const emails = await fetchEmailsViaMcp(query, 10);

    for (const email of emails) {
      if (!email.id || !email.subject) continue;

      const sourceId = `gmail_${email.id}`;
      if (eventExists("gmail", sourceId)) continue;

      if (shouldSkipEmail(email.from || "", email.subject || "", email.labels || [])) {
        continue;
      }

      // 발신자 이름 추출
      const fromName = email.from?.match(/^(.+?)\s*</)
        ? email.from.match(/^(.+?)\s*</)![1].replace(/"/g, "").trim()
        : (email.from || "Unknown").split("@")[0];

      // 업무 메일 구분
      const isWork = (email.to || "").includes("chamchi.kr") || (email.from || "").includes("chamchi.kr");

      let event: OnlimeEvent = {
        id: uuid(),
        timestamp: email.date ? new Date(email.date).toISOString() : new Date().toISOString(),
        participants: [fromName],
        type: "email",
        title: email.subject,
        body: [
          `# ${email.subject}`,
          "",
          `**From:** ${email.from}`,
          `**To:** ${email.to}`,
          `**Date:** ${email.date}`,
          isWork ? `**Account:** 업무 (chamchi.kr)` : `**Account:** 개인`,
          "",
          email.snippet || "",
        ].join("\n"),
        source: "gmail",
        source_id: sourceId,
        status: "raw",
        tags: [
          ...(email.labels || []).filter(l => !l.startsWith("CATEGORY_")),
          isWork ? "업무메일" : "개인메일",
        ],
        related: [],
      };

      event = enrichEvent(event);
      const filePath = await writeEventNote(event);
      event.obsidian_path = filePath;
      insertEvent(event);
      totalNew++;

      const accountTag = isWork ? "📧업무" : "📧개인";
      console.log(`[gmail-mcp] ${accountTag} ${email.subject.slice(0, 50)}`);
    }
  }

  if (totalNew > 0) {
    await notify("Onlime Gmail", `${totalNew}건 수집`);
  }

  return totalNew;
}
