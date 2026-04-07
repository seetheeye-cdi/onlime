/**
 * Google OAuth2 인증 스크립트
 *
 * 사전 준비:
 * 1. Google Cloud Console → API & Services → Credentials
 * 2. OAuth 2.0 Client ID 생성 (Desktop App)
 * 3. JSON 다운로드 → ~/.onlime/google-credentials.json 으로 저장
 * 4. Gmail API + Google Calendar API 활성화
 *
 * 실행: npx tsx src/scripts/gmail-auth.ts
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";
import { createServer } from "node:http";
import { OAuth2Client } from "google-auth-library";

const CONFIG_DIR = join(homedir(), ".onlime");
const CREDENTIALS_PATH = join(CONFIG_DIR, "google-credentials.json");
const TOKEN_PATH = join(CONFIG_DIR, "google-token.json");

const SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/calendar.readonly",
];

async function main() {
  await mkdir(CONFIG_DIR, { recursive: true });

  let credentials;
  try {
    const raw = await readFile(CREDENTIALS_PATH, "utf-8");
    credentials = JSON.parse(raw);
  } catch {
    console.error(`❌ Credentials not found at ${CREDENTIALS_PATH}`);
    console.log("\n📋 Setup instructions:");
    console.log("1. Go to https://console.cloud.google.com/apis/credentials");
    console.log("2. Create OAuth 2.0 Client ID (type: Desktop App)");
    console.log("3. Download JSON and save to:", CREDENTIALS_PATH);
    console.log("4. Enable Gmail API and Google Calendar API");
    console.log("5. Run this script again");
    process.exit(1);
  }

  const { client_id, client_secret } = credentials.installed || credentials.web;
  const redirect_uri = "http://localhost:3847/callback";

  const oauth2 = new OAuth2Client(client_id, client_secret, redirect_uri);

  const authUrl = oauth2.generateAuthUrl({
    access_type: "offline",
    scope: SCOPES,
    prompt: "consent",
  });

  console.log("\n🔐 Google OAuth2 인증");
  console.log("아래 URL을 브라우저에서 여세요:\n");
  console.log(authUrl);
  console.log("\n⏳ 인증 완료를 기다리는 중...");

  // 로컬 서버에서 콜백 대기
  const code = await new Promise<string>((resolve) => {
    const server = createServer((req, res) => {
      const url = new URL(req.url!, `http://localhost:3847`);
      const code = url.searchParams.get("code");

      if (code) {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end("<h1>✅ 인증 완료!</h1><p>이 창을 닫아도 됩니다.</p>");
        server.close();
        resolve(code);
      } else {
        res.writeHead(400);
        res.end("No code received");
      }
    });

    server.listen(3847, () => {
      console.log("콜백 서버 대기 중 (localhost:3847)...");
    });
  });

  // 토큰 교환
  const { tokens } = await oauth2.getToken(code);
  await writeFile(TOKEN_PATH, JSON.stringify(tokens, null, 2));

  console.log(`\n✅ 토큰 저장 완료: ${TOKEN_PATH}`);
  console.log("Gmail + Calendar API 사용 준비 완료!");
}

main().catch((err) => {
  console.error("Error:", err);
  process.exit(1);
});
