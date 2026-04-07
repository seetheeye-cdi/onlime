import { findPersonByAlias, findProjectByKeyword, updateLastContact } from "./db.js";
import type { OnlimeEvent } from "./types.js";

/**
 * 규칙 기반 이벤트 보강 — AI 없음, 정확 일치만
 * 1. 참여자 이름 → [[위키링크]] 변환
 * 2. 본문 내 프로젝트 키워드 → project 필드 매칭
 * 3. 본문 내 사람 이름 → [[위키링크]] 치환
 */
export function enrichEvent(event: OnlimeEvent): OnlimeEvent {
  const enriched = { ...event };

  // 1. 참여자 → 위키링크 매칭
  const enrichedParticipants: string[] = [];
  for (const name of event.participants) {
    const wikilink = matchPerson(name);
    enrichedParticipants.push(wikilink ?? name);
  }
  enriched.participants = enrichedParticipants;

  // 2. 프로젝트 매칭 (본문 + 제목에서 키워드 검색)
  const searchText = `${event.title || ""} ${event.body}`;
  const projectLink = matchProject(searchText);
  if (projectLink) {
    enriched.project = projectLink;
  }

  // 3. 본문 내 사람 이름 → 위키링크 치환
  enriched.body = replaceNamesWithLinks(enriched.body);

  // 4. last_contact 업데이트
  for (const p of enrichedParticipants) {
    if (p.startsWith("[[") && p !== "[[Unknown:") {
      updateLastContact(p, event.timestamp.split("T")[0]);
    }
  }

  enriched.status = "enriched";
  return enriched;
}

/**
 * 정확 일치로 사람 찾기. 퍼지 매칭 금지.
 */
export function matchPerson(name: string): string | null {
  // 1. 정확 일치
  const person = findPersonByAlias(name);
  if (person) return person.wikilink;

  // 2. 카카오톡 표시 이름 분리 매칭: "워크모어 이찬영" → "이찬영" 시도
  //    공백으로 분리된 각 부분을 개별 매칭
  if (name.includes(" ")) {
    const parts = name.split(/\s+/);
    for (const part of parts) {
      if (part.length >= 2 && part !== "(me)") {
        const found = findPersonByAlias(part);
        if (found) return found.wikilink;
      }
    }
  }

  return null;
}

/**
 * 본문에서 프로젝트 키워드 매칭
 */
export function matchProject(text: string): string | null {
  const project = findProjectByKeyword(text);
  return project?.wikilink ?? null;
}

/**
 * 본문 내 알려진 사람 이름을 [[위키링크]]로 치환
 * 성능: people 테이블이 작으므로 (<500명) 전수 검색 OK
 */
function replaceNamesWithLinks(body: string): string {
  // DB에서 모든 사람 로드하는 대신, 본문에서 추출된 이름만 매칭
  // (전수 검색은 people-loader에서 캐시 후 사용)
  // 여기서는 이미 participants에서 매칭된 이름들만 치환

  // 간단한 패턴: "**HH:MM** 이름:" 에서 이름 부분을 치환
  return body.replace(
    /(\*\*\d{1,2}:\d{2}\*\*)\s+([^:]+):/g,
    (_match, time: string, name: string) => {
      const trimmedName = name.trim();
      const person = findPersonByAlias(trimmedName);
      if (person) {
        return `${time} ${person.wikilink}:`;
      }
      return `${time} ${trimmedName}:`;
    }
  );
}
