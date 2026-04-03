#!/usr/bin/env python3
"""
Obsidian Vault Migration Script
================================
Restructures vault from INPUT-THINK-OUTPUT to Johnny Decimal numbering.

Usage:
    python scripts/migrate_vault.py --dry-run     # Preview changes
    python scripts/migrate_vault.py --execute      # Execute migration
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
PROJECT_ROOT = Path("/Users/cdiseetheeye/Desktop/Onlime")

SKIP_DIRS = {".obsidian", ".claude", ".omc", ".smtcmp_json_db", ".trash", ".git"}

NEW_FOLDERS = [
    "0. System",
    "0. System/0.1 Templates",
    "0. System/0.2 Attachments",
    "0. System/0.3 MOC",
    "1. Input",
    "1. Input/1.1 Inbox",
    "1. Input/1.2 Meeting",
    "1. Input/1.3 Book",
    "1. Input/1.4 Article",
    "1. Input/1.5 Class",
    "1. Input/1.6 Media",
    "1. Input/1.7 Term",
    "1. Input/1.8 Quote",
    "2. People",
    "2. People/2.1 Active",
    "2. People/2.2 Network",
    "2. People/2.3 Reference",
    "3. Think",
    "3. Think/3.1 Daily",
    "3. Think/3.2 Projects",
    "3. Think/3.2 Projects/참치상사",
    "3. Think/3.2 Projects/더해커톤",
    "3. Think/3.2 Projects/에이아이당",
    "3. Think/3.2 Projects/넥스트노벨",
    "3. Think/3.2 Projects/한성",
    "3. Think/3.3 Explore",
    "3. Think/3.4 Decision",
    "4. Output",
    "4. Output/4.1 Questions",
    "4. Output/4.2 Writing",
    "4. Output/4.3 Business",
    "9. Archive",
    "9. Archive/9.1 Legacy",
    "9. Archive/9.2 Empty",
]

# source_dir → dest_dir (relative to vault root)
DIRECT_MAPPINGS = [
    ("0. INPUT/Meeting", "1. Input/1.2 Meeting"),
    ("0. INPUT/Book", "1. Input/1.3 Book"),
    ("0. INPUT/Article", "1. Input/1.4 Article"),
    ("0. INPUT/Clippings", "1. Input/1.4 Article"),
    ("0. INPUT/Class", "1. Input/1.5 Class"),
    ("0. INPUT/Youtube", "1. Input/1.6 Media"),
    ("0. INPUT/Term", "1. Input/1.7 Term"),
    ("0. INPUT/Words", "1. Input/1.8 Quote"),
    ("0. INPUT/Poem", "1. Input/1.8 Quote"),
    ("0. INPUT/AI Chat", "1. Input/1.1 Inbox"),
    ("0. INPUT/excalidraw", "0. System/0.2 Attachments"),
    ("1. THINK/참치상사", "3. Think/3.2 Projects/참치상사"),
    ("1. THINK/한성", "3. Think/3.2 Projects/한성"),
    ("1. THINK/네트워크", "3. Think/3.3 Explore"),
    ("2. OUTPUT/2.0. 질문", "4. Output/4.1 Questions"),
    ("others/90. Settings/91. Templates", "0. System/0.1 Templates"),
    ("others/copilot-custom-prompts", "0. System/copilot-custom-prompts"),
    ("others/90. Settings/99. File class System", "9. Archive/9.1 Legacy"),
]

# 사이드 subfolders that are real projects → 3.2 Projects/<name>
SIDE_PROJECTS = {"넥스트노벨", "더해커톤", "에이아이당"}

# Keywords to detect project-related files among unclassified INPUT
PROJECT_KEYWORDS = {
    "참치": "3. Think/3.2 Projects/참치상사",
    "참치상사": "3. Think/3.2 Projects/참치상사",
    "chamchi": "3. Think/3.2 Projects/참치상사",
    "해커톤": "3. Think/3.2 Projects/더해커톤",
    "에이아이당": "3. Think/3.2 Projects/에이아이당",
    "AI당": "3. Think/3.2 Projects/에이아이당",
    "넥스트노벨": "3. Think/3.2 Projects/넥스트노벨",
    "한성": "3. Think/3.2 Projects/한성",
}

MEETING_PATTERNS = [
    re.compile(r"\(\d{2}\.\d{2}\.\d{2}\.?\)"),
    re.compile(r"회의"),
    re.compile(r"미팅"),
    re.compile(r"[Mm]eeting"),
]

# Korean name: 2-4 hangul syllables (가-힣), optionally followed by _role or (affil)
KOREAN_NAME_RE = re.compile(r"^[가-힣]{2,4}$")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}

# Known historical / public reference figures (partial list; expanded by heuristics)
REFERENCE_FIGURES = {
    "마르틴 하이데거", "자크 라캉", "칭기즈칸", "지그문트 프로이트",
    "마르쿠스 아우렐리우스", "마거릿 대처", "마를린 먼로", "한병철",
    "소크라테스", "플라톤", "아리스토텔레스", "니체", "칸트",
    "공자", "노자", "장자", "맹자", "손자",
    "나폴레옹", "셰익스피어", "도스토예프스키", "톨스토이", "카프카",
    "아인슈타인", "뉴턴", "다빈치", "미켈란젤로",
    "간디", "만델라", "링컨", "처칠", "루즈벨트",
    "마르크스", "막스 베버", "하이에크", "케인즈",
    "샘 알트만", "마크 저커버그", "버락 오바마", "일론 머스크",
    "이명박", "홍준표", "서경덕", "허준이", "기형도",
    "스테판 커리", "탈레스", "순다르 피차이", "임마누엘 마크롱",
    "스티브 잡스", "빌 게이츠", "워런 버핏", "제프 베조스",
    "피터 틸", "폴 그레이엄",
}

# Emoji regex — catches most common emoji + variation selectors + ZWJ sequences
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAD6"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U0000FE0F"
    "\U0000200D"
    "\U00002640-\U00002642"
    "\U00002600-\U000026FF"
    "\U0000200B-\U0000200F"
    "\U00002069"
    "\U00003030"
    "]+",
    re.UNICODE,
)

# Broken tag patterns in frontmatter
BROKEN_TAG_RES = [
    (re.compile(r"tags:\s*\[(\s*1\s*,?\s*)+\]"), "tags: []"),
    (re.compile(r"#fn\b"), ""),
    (re.compile(r"#[0-9a-fA-F]{6}\b"), ""),
    (re.compile(r"#Theme/\S*"), ""),
]


# ─── Utilities ───────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """Parse YAML frontmatter from markdown text. Returns (fm_dict, body)."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    import yaml
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return None, text
    body = text[end + 4:]  # skip \n---
    return fm, body


def dump_frontmatter(fm: dict, body: str) -> str:
    """Reconstruct markdown with frontmatter."""
    import yaml
    fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return f"---\n{fm_str}---{body}"


def is_empty_note(path: Path) -> bool:
    """Check if a note has no meaningful content beyond template boilerplate."""
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False

    if len(content.strip()) == 0:
        return True

    # Remove frontmatter
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            content = content[end + 4:]

    # Remove dataview/dataviewjs blocks
    content = re.sub(r"```(?:dataview|dataviewjs).*?```", "", content, flags=re.DOTALL)
    # Remove templater expressions
    content = re.sub(r"<%.*?%>", "", content, flags=re.DOTALL)
    # Remove navigation links like [[date|◀︎]]
    content = re.sub(r"\[\[.*?\|[◀▶︎]+\]\]", "", content)
    # Remove section headers
    content = re.sub(r"^#{1,6}\s+.*$", "", content, flags=re.MULTILINE)
    # Remove horizontal rules
    content = re.sub(r"^---+$", "", content, flags=re.MULTILINE)
    # Remove callout syntax
    content = re.sub(r"^>\s*\[!.*?\].*$", "", content, flags=re.MULTILINE)
    # Remove ==markers==
    content = re.sub(r"==", "", content)

    stripped = content.strip()
    return len(stripped) < 20


def strip_emoji(name: str) -> str:
    """Remove emoji characters from a filename, plus trim whitespace."""
    cleaned = EMOJI_RE.sub("", name).strip()
    # Also remove 🏷-style prefix markers like "🏷 " already handled by regex
    return cleaned


# ─── Migrator ────────────────────────────────────────────────────────────

class VaultMigrator:
    def __init__(self, vault: Path, project: Path, dry_run: bool = True):
        self.vault = vault
        self.project = project
        self.dry_run = dry_run
        self.renames: dict[str, str] = {}   # old_stem → new_stem
        self.stats: dict[str, int] = defaultdict(int)

    # --- helpers ---

    def log(self, msg: str):
        print(msg)

    def move_file(self, src: Path, dst_dir: Path, new_name: str | None = None):
        """Move one file into dst_dir. Handles duplicates."""
        if not src.exists():
            return
        name = new_name or src.name
        dst = dst_dir / name

        if not self.dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
            if dst.exists() and dst != src:
                base, ext = dst.stem, dst.suffix
                i = 1
                while dst.exists():
                    dst = dst_dir / f"{base}_{i}{ext}"
                    i += 1
            shutil.move(str(src), str(dst))

        old_stem = src.stem
        new_stem = dst.stem
        if old_stem != new_stem:
            self.renames[old_stem] = new_stem

        self.stats["files_moved"] += 1
        rel_src = src.relative_to(self.vault) if src.is_relative_to(self.vault) else src
        rel_dst = dst.relative_to(self.vault) if dst.is_relative_to(self.vault) else dst
        self.log(f"  MOVE: {rel_src} → {rel_dst}")

    def move_contents(self, src_rel: str, dst_rel: str):
        """Move all files from src_dir to dst_dir, preserving subdirectory structure."""
        src_dir = self.vault / src_rel
        dst_dir = self.vault / dst_rel
        if not src_dir.exists():
            self.log(f"  SKIP (not found): {src_rel}")
            return
        files = sorted(f for f in src_dir.rglob("*") if f.is_file())
        for f in files:
            rel = f.relative_to(src_dir)
            self.move_file(f, dst_dir / rel.parent)

    def rename_file(self, path: Path, new_name: str):
        """Rename a file in place."""
        if new_name == path.name:
            return
        dst = path.parent / new_name
        old_stem = path.stem
        new_stem = Path(new_name).stem
        if old_stem != new_stem:
            self.renames[old_stem] = new_stem

        if not self.dry_run:
            if dst.exists():
                base, ext = Path(new_name).stem, Path(new_name).suffix
                i = 1
                while dst.exists():
                    dst = path.parent / f"{base}_{i}{ext}"
                    i += 1
            path.rename(dst)

        self.stats["files_renamed"] += 1
        self.log(f"  RENAME: {path.name} → {new_name}")

    # ------------------------------------------------------------------
    # Phase 1: Backup
    # ------------------------------------------------------------------

    def phase_1_backup(self):
        self.log("\n=== Phase 1: Backup ===")
        stamp = datetime.now().strftime("%Y%m%d")
        backup_dir = self.vault.parent / f"Obsidian_sinc_backup_{stamp}"
        if self.dry_run:
            self.log(f"  BACKUP → {backup_dir}")
            return
        if backup_dir.exists():
            self.log(f"  Backup already exists: {backup_dir}")
            return
        self.log(f"  Copying vault to {backup_dir} ...")
        shutil.copytree(
            str(self.vault), str(backup_dir),
            ignore=shutil.ignore_patterns(".git"),
        )
        self.log("  Backup complete.")

    # ------------------------------------------------------------------
    # Phase 2: Create new folder structure
    # ------------------------------------------------------------------

    def phase_2_create_folders(self):
        self.log("\n=== Phase 2: Create New Folder Structure ===")
        for folder in NEW_FOLDERS:
            p = self.vault / folder
            if p.exists():
                continue
            self.stats["folders_created"] += 1
            self.log(f"  CREATE: {folder}/")
            if not self.dry_run:
                p.mkdir(parents=True, exist_ok=True)
        self.log(f"  Total: {self.stats['folders_created']} new folders")

    # ------------------------------------------------------------------
    # Phase 3: Direct mapping moves
    # ------------------------------------------------------------------

    def phase_3_direct_mappings(self):
        self.log("\n=== Phase 3: Direct Mapping Moves ===")

        # 3a. Move root-level .md files → Inbox
        self.log("\n  --- Root .md files → 1.1 Inbox ---")
        for f in sorted(self.vault.glob("*.md")):
            self.move_file(f, self.vault / "1. Input/1.1 Inbox")

        # 3b. Move root-level images → Attachments
        self.log("\n  --- Root images → 0.2 Attachments ---")
        for f in sorted(self.vault.iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                self.move_file(f, self.vault / "0. System/0.2 Attachments")

        # 3c. Direct directory mappings
        for src_rel, dst_rel in DIRECT_MAPPINGS:
            self.log(f"\n  --- {src_rel} → {dst_rel} ---")
            self.move_contents(src_rel, dst_rel)

        # 3d. 사이드 directory — split projects vs explore
        self.log("\n  --- 1. THINK/사이드 → Projects + Explore ---")
        side_dir = self.vault / "1. THINK/사이드"
        if side_dir.exists():
            for item in sorted(side_dir.iterdir()):
                if item.name.startswith("."):
                    continue
                if item.is_dir() and item.name in SIDE_PROJECTS:
                    dst = f"3. Think/3.2 Projects/{item.name}"
                    self.log(f"\n  --- 사이드/{item.name} → {dst} (project) ---")
                    self.move_contents(f"1. THINK/사이드/{item.name}", dst)
                else:
                    if item.is_dir():
                        self.move_contents(
                            f"1. THINK/사이드/{item.name}",
                            f"3. Think/3.3 Explore/{item.name}",
                        )
                    else:
                        self.move_file(item, self.vault / "3. Think/3.3 Explore")

        # 3e. Remaining loose files in 1. THINK/ → Explore
        self.log("\n  --- 1. THINK/ loose files → Explore ---")
        think_dir = self.vault / "1. THINK"
        if think_dir.exists():
            for item in sorted(think_dir.iterdir()):
                if item.name.startswith("."):
                    continue
                # Skip already-handled directories
                if item.is_dir() and item.name in {
                    "매일", "참치상사", "한성", "사이드", "네트워크",
                }:
                    continue
                if item.is_dir():
                    self.move_contents(
                        f"1. THINK/{item.name}",
                        f"3. Think/3.3 Explore/{item.name}",
                    )
                elif item.is_file():
                    self.move_file(item, self.vault / "3. Think/3.3 Explore")

        # 3f. Remaining loose files in 2. OUTPUT/ → Writing
        self.log("\n  --- 2. OUTPUT/ loose files → Writing ---")
        out_dir = self.vault / "2. OUTPUT"
        if out_dir.exists():
            for item in sorted(out_dir.iterdir()):
                if item.name.startswith("."):
                    continue
                if item.name == "2.0. 질문":
                    continue  # already handled
                if item.is_dir():
                    self.move_contents(
                        f"2. OUTPUT/{item.name}",
                        f"4. Output/4.2 Writing/{item.name}",
                    )
                elif item.is_file():
                    self.move_file(item, self.vault / "4. Output/4.2 Writing")

    # ------------------------------------------------------------------
    # Phase 4: Classify 671 unclassified INPUT root files
    # ------------------------------------------------------------------

    def phase_4_classify_input(self):
        self.log("\n=== Phase 4: Classify Unclassified INPUT Files ===")
        input_dir = self.vault / "0. INPUT"
        if not input_dir.exists():
            self.log("  0. INPUT/ not found — skipping")
            return

        classified = defaultdict(int)
        for f in sorted(input_dir.iterdir()):
            if not f.is_file():
                continue
            name = f.stem
            dest = self._classify_input_file(f, name)
            classified[dest] += 1
            self.move_file(f, self.vault / dest)

        self.log("\n  Classification summary:")
        for dest, count in sorted(classified.items()):
            self.log(f"    {dest}: {count} files")

    def _classify_input_file(self, path: Path, name: str) -> str:
        # Rule 1: project keyword in filename
        name_lower = name.lower()
        for kw, dest in PROJECT_KEYWORDS.items():
            if kw.lower() in name_lower:
                return dest

        # Rule 2: meeting pattern in filename
        for pat in MEETING_PATTERNS:
            if pat.search(name):
                return "1. Input/1.2 Meeting"

        # Rule 3: Korean 2-4 char name → likely a person → Network
        clean = strip_emoji(name).split("_")[0].split("(")[0].strip()
        if KOREAN_NAME_RE.match(clean):
            return "2. People/2.2 Network"

        # Rule 4: frontmatter type field
        try:
            text = path.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(text)
            if fm and isinstance(fm, dict):
                ftype = fm.get("type")
                if isinstance(ftype, str):
                    ftype = ftype.lower().strip()
                elif isinstance(ftype, list) and ftype:
                    ftype = str(ftype[0]).lower().strip()
                else:
                    ftype = None
                if ftype:
                    type_map = {
                        "person": "2. People/2.2 Network",
                        "meeting": "1. Input/1.2 Meeting",
                        "book": "1. Input/1.3 Book",
                        "article": "1. Input/1.4 Article",
                        "class": "1. Input/1.5 Class",
                        "term": "1. Input/1.7 Term",
                        "quote": "1. Input/1.8 Quote",
                        "poem": "1. Input/1.8 Quote",
                        "decision": "3. Think/3.4 Decision",
                    }
                    if ftype in type_map:
                        return type_map[ftype]
        except (UnicodeDecodeError, OSError):
            pass

        # Rule 5: fallback → Inbox
        return "1. Input/1.1 Inbox"

    # ------------------------------------------------------------------
    # Phase 5: Classify People (159 files)
    # ------------------------------------------------------------------

    def phase_5_classify_people(self):
        self.log("\n=== Phase 5: Classify People ===")
        people_dir = self.vault / "0. INPUT/People"
        if not people_dir.exists():
            self.log("  0. INPUT/People/ not found — skipping")
            return

        classified = defaultdict(int)
        for f in sorted(people_dir.rglob("*")):
            if not f.is_file() or f.suffix.lower() != ".md":
                # Move non-md files (images etc.) to Attachments
                if f.is_file():
                    self.move_file(f, self.vault / "0. System/0.2 Attachments")
                continue
            dest = self._classify_person(f)
            classified[dest] += 1
            self.move_file(f, self.vault / dest)

        self.log("\n  People classification summary:")
        for dest, count in sorted(classified.items()):
            self.log(f"    {dest}: {count}")

    def _classify_person(self, path: Path) -> str:
        name = strip_emoji(path.stem).strip()

        # Check against known reference figures
        if name in REFERENCE_FIGURES:
            return "2. People/2.3 Reference"

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return "2. People/2.2 Network"

        fm, body = parse_frontmatter(text)
        has_contact = False
        has_role_info = False

        if fm and isinstance(fm, dict):
            # Rule 1: Person template + contact info → Active
            if fm.get("type") == "person":
                email = fm.get("email")
                phone = fm.get("phone")
                if email or phone:
                    return "2. People/2.1 Active"
                has_contact = True  # template present at least

            # Check for role/company fields
            if fm.get("company") or fm.get("role"):
                has_role_info = True

        # Rule 2: Korean name + affiliation/role recorded → Active
        clean_name = name.split("_")[0].split("(")[0].strip()
        is_korean = bool(KOREAN_NAME_RE.match(clean_name))

        if is_korean and (has_role_info or has_contact):
            return "2. People/2.1 Active"

        # Check body for affiliation clues: _직책, (소속), 소개, 연락처
        if is_korean and body:
            affil_patterns = ["소속", "직책", "회사", "팀", "역할", "연락", "@"]
            if any(p in body for p in affil_patterns):
                return "2. People/2.1 Active"

        # Rule 3: Non-Korean transliterated name (foreign public figure)
        if not is_korean and " " in name and len(name) > 5:
            return "2. People/2.3 Reference"

        # Rule 4: default → Network
        return "2. People/2.2 Network"

    # ------------------------------------------------------------------
    # Phase 6: Frontmatter cleanup
    # ------------------------------------------------------------------

    def phase_6_frontmatter_cleanup(self):
        self.log("\n=== Phase 6: Frontmatter Cleanup ===")
        count = 0
        # Scan all .md files in new structure
        for md in sorted(self.vault.rglob("*.md")):
            if any(skip in md.parts for skip in SKIP_DIRS):
                continue
            if self._cleanup_frontmatter(md):
                count += 1
        self.stats["frontmatter_cleaned"] = count
        self.log(f"  Cleaned {count} files")

    def _cleanup_frontmatter(self, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return False

        original = text
        modified = False

        # Clean broken tags in raw text
        for pattern, replacement in BROKEN_TAG_RES:
            new_text = pattern.sub(replacement, text)
            if new_text != text:
                text = new_text
                modified = True

        # Parse frontmatter for deeper fixes
        fm, body = parse_frontmatter(text)
        if fm and isinstance(fm, dict):
            # Remove null/empty fields
            to_remove = [k for k, v in fm.items() if v is None and k != "type"]
            for k in to_remove:
                del fm[k]
                modified = True

            # Clean tags field
            tags = fm.get("tags")
            if isinstance(tags, list):
                clean_tags = [
                    t for t in tags
                    if isinstance(t, str) and t.strip()
                    and not re.match(r"^[0-9a-fA-F]{6}$", t)
                    and t not in ("fn", "1")
                ]
                if clean_tags != tags:
                    fm["tags"] = clean_tags if clean_tags else []
                    modified = True

            # Rebuild if modified
            if modified:
                text = dump_frontmatter(fm, body)

        if modified and text != original:
            if self.dry_run:
                rel = path.relative_to(self.vault)
                self.log(f"  CLEAN: {rel}")
            else:
                path.write_text(text, encoding="utf-8")
            return True
        return False

    # ------------------------------------------------------------------
    # Phase 7: Emoji prefix removal + filename standardization
    # ------------------------------------------------------------------

    def phase_7_emoji_rename(self):
        self.log("\n=== Phase 7: Emoji Removal & Filename Standardization ===")
        count = 0
        for md in sorted(self.vault.rglob("*.md")):
            if any(skip in md.parts for skip in SKIP_DIRS):
                continue
            old_name = md.stem
            new_name = strip_emoji(old_name).strip()
            if not new_name:
                continue
            if new_name != old_name:
                self.rename_file(md, new_name + md.suffix)
                count += 1
        self.log(f"  Renamed {count} files")

    # ------------------------------------------------------------------
    # Phase 8: Empty daily notes → Archive
    # ------------------------------------------------------------------

    def phase_8_empty_daily(self):
        self.log("\n=== Phase 8: Process Daily Notes (split empty / content) ===")
        daily_src = self.vault / "1. THINK/매일"
        if not daily_src.exists():
            self.log("  1. THINK/매일/ not found — skipping")
            return

        empty_count = 0
        content_count = 0

        for f in sorted(daily_src.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower() == ".md" and is_empty_note(f):
                self.move_file(f, self.vault / "9. Archive/9.2 Empty")
                empty_count += 1
            else:
                self.move_file(f, self.vault / "3. Think/3.1 Daily")
                content_count += 1

        self.log(f"  Content notes → Daily: {content_count}")
        self.log(f"  Empty notes → Archive: {empty_count}")

    # ------------------------------------------------------------------
    # Phase 9: COLLECT legacy processing
    # ------------------------------------------------------------------

    def phase_9_collect_legacy(self):
        self.log("\n=== Phase 9: COLLECT Legacy Processing ===")
        collect_dir = self.vault / "0. INPUT/COLLECT"
        if not collect_dir.exists():
            self.log("  0. INPUT/COLLECT/ not found — skipping")
            return

        # Move 00. Inbox contents to new Inbox first
        inbox_sub = collect_dir / "00. Inbox"
        if inbox_sub.exists():
            self.log("  --- COLLECT/00. Inbox → 1.1 Inbox ---")
            self.move_contents("0. INPUT/COLLECT/00. Inbox", "1. Input/1.1 Inbox")

        # Move everything else to Legacy
        self.log("  --- COLLECT remaining → 9.1 Legacy ---")
        if collect_dir.exists():
            for item in sorted(collect_dir.rglob("*")):
                if item.is_file():
                    rel = item.relative_to(collect_dir)
                    self.move_file(
                        item,
                        self.vault / "9. Archive/9.1 Legacy" / rel.parent,
                    )

    # ------------------------------------------------------------------
    # Phase 10: Update wikilinks for renamed files
    # ------------------------------------------------------------------

    def phase_10_wikilinks(self):
        self.log("\n=== Phase 10: Update Wikilinks ===")
        if not self.renames:
            self.log("  No renames to update.")
            return

        self.log(f"  {len(self.renames)} files were renamed. Scanning for wikilinks...")

        # Build regex that matches any old stem in a wikilink
        # Sort by length descending to match longer names first
        sorted_old = sorted(self.renames.keys(), key=len, reverse=True)
        escaped = [re.escape(n) for n in sorted_old]
        wl_pattern = re.compile(
            r"\[\[(" + "|".join(escaped) + r")([#|][^\]]*?)?\]\]"
        )

        update_count = 0
        file_count = 0

        for md in sorted(self.vault.rglob("*.md")):
            if any(skip in md.parts for skip in SKIP_DIRS):
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            def replace_link(m):
                old = m.group(1)
                suffix_part = m.group(2) or ""
                new = self.renames.get(old, old)
                return f"[[{new}{suffix_part}]]"

            new_text = wl_pattern.sub(replace_link, text)
            if new_text != text:
                update_count += new_text != text  # always 1 if different
                file_count += 1
                if self.dry_run:
                    rel = md.relative_to(self.vault)
                    self.log(f"  UPDATE: {rel}")
                else:
                    md.write_text(new_text, encoding="utf-8")

        self.log(f"  Updated wikilinks in {file_count} files")

    # ------------------------------------------------------------------
    # Phase 11: Generate MOC (Map of Content) files
    # ------------------------------------------------------------------

    def phase_11_moc(self):
        self.log("\n=== Phase 11: Generate MOC Files ===")
        moc_dir = self.vault / "0. System/0.3 MOC"

        mocs = {
            "MOC People.md": self._moc_people(),
            "MOC Projects.md": self._moc_projects(),
            "MOC Daily Notes.md": self._moc_daily(),
            "MOC Knowledge.md": self._moc_knowledge(),
            "MOC Output.md": self._moc_output(),
        }

        for name, content in mocs.items():
            path = moc_dir / name
            self.log(f"  CREATE: 0.3 MOC/{name}")
            if not self.dry_run:
                moc_dir.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            self.stats["mocs_created"] += 1

    def _moc_people(self) -> str:
        return """---
type: moc
---
# MOC People

## Active Contacts
```dataview
TABLE role, company, phone
FROM "2. People/2.1 Active"
SORT file.name ASC
```

## Network
```dataview
LIST
FROM "2. People/2.2 Network"
SORT file.name ASC
```

## Reference Figures
```dataview
LIST
FROM "2. People/2.3 Reference"
SORT file.name ASC
```

## Recent Meetings by Person
```dataview
TABLE WITHOUT ID
  file.link AS "Meeting",
  dateformat(date(file.name), "yyyy-MM-dd") AS "Date"
FROM "1. Input/1.2 Meeting"
WHERE contains(file.outlinks, this.file.link)
SORT file.name DESC
LIMIT 20
```
"""

    def _moc_projects(self) -> str:
        projects = ["참치상사", "더해커톤", "에이아이당", "넥스트노벨", "한성"]
        sections = []
        for p in projects:
            sections.append(f"""## {p}
```dataview
TABLE file.mtime AS "Modified"
FROM "3. Think/3.2 Projects/{p}"
SORT file.mtime DESC
LIMIT 10
```
""")
        return f"""---
type: moc
---
# MOC Projects

{"".join(sections)}"""

    def _moc_daily(self) -> str:
        return """---
type: moc
---
# MOC Daily Notes

## Recent Daily Notes
```dataview
LIST
FROM "3. Think/3.1 Daily"
SORT file.name DESC
LIMIT 14
```

## Weekly Reviews
```dataview
LIST
FROM "3. Think/3.1 Daily"
WHERE contains(file.name, "Weekly")
SORT file.name DESC
```
"""

    def _moc_knowledge(self) -> str:
        return """---
type: moc
---
# MOC Knowledge

## Books
```dataview
TABLE author, type
FROM "1. Input/1.3 Book"
SORT file.name ASC
```

## Terms & Concepts
```dataview
LIST
FROM "1. Input/1.7 Term"
SORT file.name ASC
```

## Most Connected Notes
```dataview
TABLE length(file.inlinks) AS "Backlinks", length(file.outlinks) AS "Outlinks"
FROM ""
WHERE length(file.inlinks) > 3
SORT length(file.inlinks) DESC
LIMIT 20
```
"""

    def _moc_output(self) -> str:
        return """---
type: moc
---
# MOC Output

## Questions Series
```dataview
LIST
FROM "4. Output/4.1 Questions"
SORT file.name ASC
```

## Writing
```dataview
LIST
FROM "4. Output/4.2 Writing"
SORT file.mtime DESC
```

## Business Documents
```dataview
LIST
FROM "4. Output/4.3 Business"
SORT file.mtime DESC
```
"""

    # ------------------------------------------------------------------
    # Phase 12: Update configuration files
    # ------------------------------------------------------------------

    def phase_12_config(self):
        self.log("\n=== Phase 12: Update Configuration Files ===")

        # 12a. onlime.toml
        toml_path = self.project / "onlime.toml"
        self.log(f"  UPDATE: {toml_path}")
        if not self.dry_run and toml_path.exists():
            text = toml_path.read_text(encoding="utf-8")
            text = text.replace(
                'meeting_dir = "0. INPUT/Meeting"',
                'meeting_dir = "1. Input/1.2 Meeting"',
            )
            text = text.replace(
                'daily_dir = "1. THINK/매일"',
                'daily_dir = "3. Think/3.1 Daily"',
            )
            text = text.replace(
                'inbox_dir = "0. INPUT/COLLECT/00. Inbox"',
                'inbox_dir = "1. Input/1.1 Inbox"',
            )
            text = text.replace(
                'people_dir = "0. INPUT/People"',
                'people_dir = "2. People"',
            )
            toml_path.write_text(text, encoding="utf-8")

        # 12b. settings.py
        settings_path = self.project / "src/onlime/config/settings.py"
        self.log(f"  UPDATE: {settings_path}")
        if not self.dry_run and settings_path.exists():
            text = settings_path.read_text(encoding="utf-8")
            text = text.replace(
                'meeting_dir: str = "0. INPUT/Meeting"',
                'meeting_dir: str = "1. Input/1.2 Meeting"',
            )
            text = text.replace(
                'daily_dir: str = "1. THINK/매일"',
                'daily_dir: str = "3. Think/3.1 Daily"',
            )
            text = text.replace(
                'inbox_dir: str = "0. INPUT/COLLECT/00. Inbox"',
                'inbox_dir: str = "1. Input/1.1 Inbox"',
            )
            text = text.replace(
                'people_dir: str = "0. INPUT/People"',
                'people_dir: str = "2. People"',
            )
            settings_path.write_text(text, encoding="utf-8")

        # 12c. .obsidian/daily-notes.json
        dn_path = self.vault / ".obsidian/daily-notes.json"
        self.log(f"  UPDATE: {dn_path}")
        if not self.dry_run and dn_path.exists():
            dn = json.loads(dn_path.read_text(encoding="utf-8"))
            dn["folder"] = "3. Think/3.1 Daily"
            dn["template"] = "0. System/0.1 Templates/Template_01. Daily Note"
            dn_path.write_text(
                json.dumps(dn, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        # 12d. .obsidian/templates.json
        tmpl_path = self.vault / ".obsidian/templates.json"
        self.log(f"  UPDATE: {tmpl_path}")
        if not self.dry_run and tmpl_path.exists():
            tmpl = json.loads(tmpl_path.read_text(encoding="utf-8"))
            tmpl["folder"] = "0. System/0.1 Templates"
            tmpl_path.write_text(
                json.dumps(tmpl, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    # ------------------------------------------------------------------
    # Phase 13: Cleanup empty old directories
    # ------------------------------------------------------------------

    def phase_13_cleanup(self):
        self.log("\n=== Phase 13: Cleanup Empty Old Directories ===")
        old_dirs = [
            "0. INPUT",
            "1. THINK",
            "2. OUTPUT",
            "others",
        ]
        for d in old_dirs:
            p = self.vault / d
            if not p.exists():
                continue
            # Count remaining files
            remaining = list(p.rglob("*"))
            remaining_files = [f for f in remaining if f.is_file()]
            if remaining_files:
                self.log(f"  KEEP: {d}/ ({len(remaining_files)} files remaining)")
            else:
                self.log(f"  REMOVE: {d}/ (empty)")
                if not self.dry_run:
                    shutil.rmtree(str(p), ignore_errors=True)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self):
        self.log("\n=== Verification ===")

        # Count files per top-level folder
        self.log("\n  File counts by folder:")
        for folder in sorted(self.vault.iterdir()):
            if folder.name.startswith(".") or not folder.is_dir():
                continue
            count = sum(1 for f in folder.rglob("*") if f.is_file())
            self.log(f"    {folder.name}: {count} files")

        # Check for broken wikilinks
        broken = 0
        all_stems = {f.stem for f in self.vault.rglob("*.md") if not any(s in f.parts for s in SKIP_DIRS)}
        wl_re = re.compile(r"\[\[([^\]#|]+)")
        for md in self.vault.rglob("*.md"):
            if any(s in md.parts for s in SKIP_DIRS):
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for m in wl_re.finditer(text):
                target = m.group(1).strip()
                if target and target not in all_stems:
                    broken += 1

        self.log(f"\n  Broken wikilinks: {broken}")
        self.log(f"  Total files moved: {self.stats['files_moved']}")
        self.log(f"  Total files renamed: {self.stats['files_renamed']}")
        self.log(f"  Frontmatter cleaned: {self.stats.get('frontmatter_cleaned', 0)}")
        self.log(f"  MOCs created: {self.stats.get('mocs_created', 0)}")

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self):
        mode = "DRY RUN" if self.dry_run else "EXECUTE"
        self.log(f"\n{'='*60}")
        self.log(f"  Obsidian Vault Migration — {mode}")
        self.log(f"  Vault: {self.vault}")
        self.log(f"  Time:  {datetime.now().isoformat()}")
        self.log(f"{'='*60}")

        if not self.dry_run:
            self.phase_1_backup()

        self.phase_2_create_folders()
        self.phase_8_empty_daily()       # Split daily notes BEFORE general moves
        self.phase_3_direct_mappings()
        self.phase_4_classify_input()
        self.phase_5_classify_people()
        self.phase_9_collect_legacy()
        self.phase_7_emoji_rename()      # Rename after all moves
        self.phase_6_frontmatter_cleanup()
        self.phase_10_wikilinks()        # Update links after all renames
        self.phase_11_moc()
        self.phase_12_config()

        if not self.dry_run:
            self.phase_13_cleanup()

        self.verify()

        self.log(f"\n{'='*60}")
        self.log(f"  Migration {'preview' if self.dry_run else 'complete'}!")
        self.log(f"{'='*60}")


# ─── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Migrate Obsidian vault to Johnny Decimal structure",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    group.add_argument("--execute", action="store_true", help="Execute the migration")
    parser.add_argument("--vault", type=Path, default=VAULT_ROOT, help="Vault root path")
    parser.add_argument("--project", type=Path, default=PROJECT_ROOT, help="Onlime project root")
    args = parser.parse_args()

    if not args.vault.exists():
        print(f"Error: vault not found at {args.vault}")
        sys.exit(1)

    if args.execute:
        print("\n  WARNING: This will modify your vault!")
        print("  Make sure you have a backup.")
        resp = input("  Type 'yes' to continue: ")
        if resp.strip().lower() != "yes":
            print("  Aborted.")
            sys.exit(0)

    migrator = VaultMigrator(args.vault, args.project, dry_run=args.dry_run)
    migrator.run()


if __name__ == "__main__":
    main()
