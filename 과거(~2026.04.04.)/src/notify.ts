import { execFile } from "node:child_process";
import { promisify } from "node:util";

const exec = promisify(execFile);

export async function notify(title: string, message: string): Promise<void> {
  try {
    const escaped = message.replace(/"/g, '\\"');
    const titleEscaped = title.replace(/"/g, '\\"');
    await exec("osascript", [
      "-e",
      `display notification "${escaped}" with title "${titleEscaped}"`,
    ]);
  } catch {
    // 알림 실패는 무시 (GUI 없는 환경일 수 있음)
  }
}

export async function notifyError(title: string, message: string): Promise<void> {
  try {
    const escaped = message.replace(/"/g, '\\"');
    const titleEscaped = title.replace(/"/g, '\\"');
    await exec("osascript", [
      "-e",
      `display notification "${escaped}" with title "${titleEscaped}" sound name "Basso"`,
    ]);
  } catch {
    // 알림 실패는 무시
  }
}
