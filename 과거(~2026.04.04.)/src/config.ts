import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { OnlimeConfig } from "./types.js";

const DEFAULT_CONFIG: OnlimeConfig = {
  obsidianVaultPath: "/Users/aiparty/Desktop/Obsidian_sinc",
  inputPath: "1. INPUT",
  pollIntervals: {
    kakao: 5,
    gmail: 5,
    gcal: 15,
    slack: 5,
  },
  excludeChats: [],
  watchChats: ["테크노크라츠 유민승"],
  summarizeHour: 23,
  morningBriefHour: 8,
};

export async function loadConfig(): Promise<OnlimeConfig> {
  const config = { ...DEFAULT_CONFIG };

  try {
    const raw = await readFile(
      join(import.meta.dirname, "..", "config", "onlime.json"),
      "utf-8"
    );
    const parsed = JSON.parse(raw);

    if (parsed.obsidianVaultPath) config.obsidianVaultPath = parsed.obsidianVaultPath;
    if (parsed.inputPath) config.inputPath = parsed.inputPath;
    if (parsed.pollIntervals) {
      config.pollIntervals = { ...config.pollIntervals, ...parsed.pollIntervals };
    }
    if (parsed.excludeChats) config.excludeChats = parsed.excludeChats;
    if (parsed.watchChats) config.watchChats = parsed.watchChats;
    if (parsed.summarizeHour !== undefined) config.summarizeHour = parsed.summarizeHour;
    if (parsed.morningBriefHour !== undefined) config.morningBriefHour = parsed.morningBriefHour;
  } catch {
    console.log("[config] Using default config (config/onlime.json not found)");
  }

  return config;
}
