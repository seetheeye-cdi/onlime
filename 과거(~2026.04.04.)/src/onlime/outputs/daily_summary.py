"""Daily summary — collects today's Plaud recordings, creates detail notes, injects concise summary into daily note."""
from __future__ import annotations

import re
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.plaud import (
    fetch_recordings, parse_recording_time, get_recording_id,
    get_recording_duration, fetch_summary, fetch_outline, format_outline,
    fetch_transcription, format_transcription,
)
from onlime.outputs.templates import render_template
from onlime.processors.linker import auto_link, discover_korean_english
from onlime.vault.index import VaultIndex
from onlime.vault.io import (
    daily_note_path, read_note, write_note, note_exists, create_stub_note,
)

logger = logging.getLogger(__name__)

SUMMARY_HEADING = "#### 오늘의 기록"


def _fetch_day_recordings(target_date: date) -> list[dict]:
    """Fetch and filter recordings for a specific date."""
    settings = get_settings()
    tz = ZoneInfo(settings.general.timezone)

    recordings = fetch_recordings(limit=50)
    day_recs = []
    for r in recordings:
        t = parse_recording_time(r)
        if t and t.date() == target_date and r.get("is_trans"):
            day_recs.append(r)

    day_recs.sort(key=lambda r: parse_recording_time(r) or datetime.min.replace(tzinfo=tz))
    return day_recs


def _extract_one_liner(summary_md: str) -> str:
    """Extract a single-line core summary from the full AI summary."""
    if not summary_md:
        return ""
    # Try to get the first meaningful sentence after headings
    lines = summary_md.strip().split('\n')
    for line in lines:
        line = line.strip()
        # Skip headings, empty lines, separators
        if not line or line.startswith('#') or line.startswith('---') or line.startswith('|'):
            continue
        # Skip blockquotes that are just attribution
        if line.startswith('> —') or line.startswith('> -'):
            continue
        # Clean up markdown formatting for the one-liner
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', line)  # remove bold
        text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)  # remove links
        # Truncate to reasonable length
        if len(text) > 120:
            text = text[:117] + '...'
        return text
    return ""


def _shorten_title(title: str) -> str:
    """Shorten a verbose Plaud-generated title to its core topic."""
    # Strip date prefix like "03-17 "
    title = re.sub(r'^\d{2}-\d{2}\s+', '', title)
    # Split on colon, take first part
    if ':' in title:
        title = title.split(':', 1)[0].strip()
    # If still too long, truncate at word boundary ~25 chars
    if len(title) > 25:
        words = title.split()
        result = []
        length = 0
        for w in words:
            new_len = length + len(w) + (1 if result else 0)
            if new_len > 25:
                break
            result.append(w)
            length = new_len
        title = ' '.join(result) if result else title[:25]
    return title.strip()


def _participant_display_names(participants: list[str]) -> list[str]:
    """Extract display names from participant wikilinks."""
    names = []
    for p in participants:
        m = re.match(r'\[\[([^\[\]|]+?)(?:\|([^\[\]]*?))?\]\]', p)
        if m:
            names.append(m.group(2) or m.group(1))
    return names


def _make_detail_note_name(date_str: str, title: str, participant_names: list[str] | None = None) -> str:
    """Generate the detail note filename (without .md)."""
    short = _shorten_title(title)
    safe_title = re.sub(r'[/\\:*?"<>|]', '', short).strip()
    safe_title = re.sub(r'\s+', ' ', safe_title)
    if participant_names:
        names_str = '·'.join(participant_names)
        return f"{date_str}_{names_str} - {safe_title}_Meeting"
    return f"{date_str}_{safe_title}_Meeting"


def _is_person_name(name: str) -> bool:
    """Check if a Korean string looks like a person name (2-3 pure Korean chars, starts with surname).

    Rejects names containing spaces or ASCII characters (these are concept
    entities like '양극화 Polarization', '정체성 Identity').
    """
    if not name or name.isascii():
        return False
    # Reject mixed Korean+English or multi-word (concept entities)
    if ' ' in name or any(c.isascii() and not c.isspace() for c in name):
        return False
    korean_only = ''.join(c for c in name if '\uac00' <= c <= '\ud7a3')
    return len(korean_only) == 3 and korean_only[0] in VaultIndex._KOREAN_SURNAMES


def _build_known_people() -> set[str]:
    """Build set of known meeting participants from config.

    Combines names.email_to_name values + names.known_contacts.
    This filters out famous people who are merely mentioned in summaries
    (e.g. 노무현, 안철수, 이명박) from being listed as meeting participants.
    """
    settings = get_settings()
    known: set[str] = set()
    # From email mapping: "김민재_참치개발자" → "김민재"
    for name in settings.names.email_to_name.values():
        if '_' in name:
            known.add(name.split('_', 1)[0].strip())
        else:
            known.add(name)
    # From explicit contacts list
    for name in settings.names.known_contacts:
        known.add(name.strip())
    return known


def _extract_participants(body: str, vault_index: VaultIndex | None) -> list[str]:
    """Extract person-name wikilinks from body text as participant list.

    Only includes names that:
    1. Look like Korean person names (3 pure Korean chars, starts with surname)
    2. Are in the known people set (email_to_name + known_contacts)

    This prevents famous people merely mentioned in discussion (노무현, 안철수)
    from being listed as meeting participants.
    """
    if not vault_index or not vault_index.entities:
        return []

    known_people = _build_known_people()

    # Find all [[...]] in body
    found: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'\[\[([^\[\]|]+?)(?:\|[^\[\]]*?)?\]\]', body):
        target = m.group(1).strip()
        display_name = None
        if '_' in target:
            name_part = target.split('_', 1)[0].strip()
            if _is_person_name(name_part):
                display_name = name_part
        elif _is_person_name(target):
            display_name = target

        # Only include known people (from config)
        if display_name and display_name in known_people and display_name not in seen:
            seen.add(display_name)
            found.append(f"[[{target}|{display_name}]]" if '_' in target else f"[[{target}]]")

    return found


def _create_detail_note(
    recording: dict, summary_md: str | None, outline_md: str | None,
    transcript_md: str | None, target_date: date,
    vault_index: VaultIndex | None = None, dry_run: bool = False,
) -> str:
    """Create a detail note with full summary/outline/transcript in Meeting folder.

    Returns the note name (without .md) for wiki-linking.
    """
    settings = get_settings()
    tz = ZoneInfo(settings.general.timezone)

    rec_time = parse_recording_time(recording) or datetime.now(tz=tz)
    rec_id = get_recording_id(recording)
    title = recording.get('filename', f'녹음_{rec_time.strftime("%H%M")}')
    date_str = rec_time.strftime('%Y%m%d')
    duration = get_recording_duration(recording)
    short_title = _shorten_title(title)

    # Build body
    body = f"- 일시: {rec_time.strftime('%Y-%m-%d %H:%M')}\n"
    body += f"- 길이: {int(duration.total_seconds() // 60)}분\n\n"

    # Auto-link summary and extract participants from SUMMARY ONLY
    # (outline/transcript mention people who were discussed, not attendees)
    linked_summary = None
    if summary_md:
        linked_summary = auto_link(summary_md, vault_index) if vault_index else summary_md
        body += f"{linked_summary}\n\n"

    if outline_md:
        linked = auto_link(outline_md, vault_index) if vault_index else outline_md
        body += f"{linked}\n\n"

    if transcript_md:
        body += f"{transcript_md}\n"

    # Extract participants from summary only (not full body)
    participants = _extract_participants(linked_summary or "", vault_index)
    p_names = _participant_display_names(participants)
    note_name = _make_detail_note_name(date_str, title, p_names)
    note_path = settings.vault.meeting_path / f"{note_name}.md"

    # Prepend h1 with participants + short title
    h1_parts = []
    if p_names:
        h1_parts.append('·'.join(p_names))
    h1_parts.append(short_title)
    body = f"\n# {' - '.join(h1_parts)}\n\n{body}"

    # If note already exists, apply auto_link + update frontmatter
    if note_path.exists():
        fm, existing_body = read_note(note_path)
        changed = False

        if vault_index and vault_index.entities:
            linked_body = auto_link(existing_body, vault_index)
            if linked_body != existing_body:
                existing_body = linked_body
                changed = True

        date_link = f"[[{target_date.strftime('%Y-%m-%d')}]]"
        if fm.get("date") != date_link:
            fm["date"] = date_link
            changed = True
        if participants and fm.get("participants") != participants:
            fm["participants"] = participants
            changed = True

        if changed:
            if not dry_run:
                write_note(note_path, fm, existing_body)
            logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Updated existing note: {note_name}")
        else:
            logger.info(f"Detail note already up-to-date: {note_name}")
        return note_name

    date_link = f"[[{target_date.strftime('%Y-%m-%d')}]]"
    frontmatter = {
        "created": rec_time.strftime("%Y-%m-%d %H:%M"),
        "date": date_link,
        "type": "meeting",
        "source": "plaud",
        "plaud_id": rec_id,
    }
    if participants:
        frontmatter["participants"] = participants

    if not dry_run:
        write_note(note_path, frontmatter, body)

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Created detail note: {note_name}")
    return note_name


def _discover_and_create_entities(
    all_texts: list[str],
    vault_index: VaultIndex,
    vault_root: Path,
    people_dir: str,
    entity_dir: str,
    dry_run: bool = False,
) -> dict[str, str]:
    """Discover new entities from all recording texts, create stub notes, return entity map.

    Scans all texts for 한국어(English) patterns, creates stub notes for
    entities not yet in the vault, and returns the discovered entity mappings.
    """
    discovered: dict[str, str] = {}
    for text in all_texts:
        entities = discover_korean_english(text)
        for key, link in entities.items():
            if key not in vault_index.entities and key not in discovered:
                discovered[key] = link

    if not discovered:
        return discovered

    logger.info(f"Discovered {len(discovered)} new entities from Korean(English) patterns")

    # Create stub notes for discovered entities
    for key, link in discovered.items():
        entity_name = link[2:-2]  # strip [[ and ]]
        create_stub_note(vault_root, people_dir, entity_dir, entity_name, dry_run=dry_run)

    return discovered


def build_daily_summary(target_date: date, dry_run: bool = False) -> str | None:
    """Build daily summary: create detail notes + return concise summary block for daily note."""
    settings = get_settings()
    tz = ZoneInfo(settings.general.timezone)

    recordings = _fetch_day_recordings(target_date)
    if not recordings:
        logger.info(f"No transcribed recordings for {target_date}")
        return None

    logger.info(f"Found {len(recordings)} transcribed recordings for {target_date}")

    # 1. Build vault entity index (wikilinks + filenames + watchlist)
    vault_index = VaultIndex()
    vault_index.build(
        vault_root=settings.vault.root,
        daily_path=settings.vault.daily_path,
        meeting_path=settings.vault.meeting_path,
        entity_watchlist=settings.vault.entity_watchlist,
    )

    # 2. Fetch all recording content first
    rec_contents: list[dict] = []
    all_texts: list[str] = []
    for r in recordings:
        rec_time = parse_recording_time(r)
        rec_id = get_recording_id(r)
        duration = get_recording_duration(r)
        title = r.get('filename', f'녹음_{rec_time.strftime("%H%M")}')

        summary_md = fetch_summary(rec_id) if r.get("is_summary") else None
        outline_raw = fetch_outline(rec_id)
        outline_md = format_outline(outline_raw) if outline_raw else None
        segments = fetch_transcription(rec_id)
        transcript_md = format_transcription(segments) if segments else None

        rec_contents.append({
            'recording': r,
            'rec_time': rec_time,
            'rec_id': rec_id,
            'duration': duration,
            'title': title,
            'summary_md': summary_md,
            'outline_md': outline_md,
            'transcript_md': transcript_md,
        })

        # Collect all linkable text for entity discovery
        for text in (summary_md, outline_md):
            if text:
                all_texts.append(text)

    # 3. Discover new entities across all texts → create stubs → register
    discovered = _discover_and_create_entities(
        all_texts, vault_index, settings.vault.root,
        settings.vault.people_dir, settings.vault.entity_dir,
        dry_run=dry_run,
    )
    if discovered:
        vault_index.add_entities(discovered)

    # 4. Create detail notes with enriched index
    rec_data = []
    for rc in rec_contents:
        note_name = _create_detail_note(
            rc['recording'], rc['summary_md'], rc['outline_md'],
            rc['transcript_md'], target_date,
            vault_index=vault_index, dry_run=dry_run,
        )

        one_liner = _extract_one_liner(rc['summary_md'])
        one_liner = auto_link(one_liner, vault_index)

        rec_data.append({
            'time': rc['rec_time'].strftime('%H:%M') if rc['rec_time'] else '??:??',
            'title': rc['title'],
            'duration': int(rc['duration'].total_seconds() // 60),
            'note_name': note_name,
            'one_liner': one_liner,
        })

    return render_template('daily_summary.md.j2', recordings=rec_data)


def inject_daily_summary(target_date: date | None = None, dry_run: bool = False) -> None:
    """Inject daily summary into the daily note after '## ==잡서'."""
    settings = get_settings()

    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%Y-%m-%d')
    path = daily_note_path(settings.vault.daily_path, date_str)

    if not note_exists(path):
        logger.info(f"Daily note {date_str}.md does not exist, skipping")
        return

    summary_block = build_daily_summary(target_date, dry_run=dry_run)
    if not summary_block:
        logger.info("No summary to inject")
        return

    fm, body = read_note(path)

    heading = "## ==잡서"
    heading_idx = body.find(heading)

    # Check if summary already exists — replace it
    existing_idx = body.find(SUMMARY_HEADING)
    if existing_idx != -1:
        rest = body[existing_idx + len(SUMMARY_HEADING):]
        end_offset = len(rest)
        for marker in ['\n#### ', '\n### ', '\n## ', '\n---']:
            pos = rest.find(marker)
            if pos != -1 and pos < end_offset:
                end_offset = pos

        body = body[:existing_idx] + summary_block.rstrip() + '\n' + body[existing_idx + len(SUMMARY_HEADING) + end_offset:]
        logger.info(f"Replaced existing daily summary in {path.name}")
    elif heading_idx != -1:
        after_heading = heading_idx + len(heading)
        if after_heading < len(body) and body[after_heading] == '\n':
            after_heading += 1

        separator_idx = body.find('\n---\n', after_heading)
        if separator_idx != -1:
            body = body[:separator_idx] + '\n' + summary_block.rstrip() + '\n' + body[separator_idx:]
        else:
            body = body[:after_heading] + summary_block.rstrip() + '\n\n' + body[after_heading:]

        logger.info(f"Injected daily summary into {path.name}")
    else:
        body = body.rstrip() + '\n\n' + summary_block.rstrip() + '\n'
        logger.info(f"Appended daily summary to {path.name}")

    if not dry_run:
        write_note(path, fm, body)

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Daily summary for {date_str}")
