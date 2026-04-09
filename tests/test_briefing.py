from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import onlime.briefing as briefing
from onlime.config import Settings


class FakeSearch:
    def __init__(self, results_map):
        self._results_map = results_map

    async def search(self, query: str, limit: int = 10, category: str | None = None):
        key = (query, category)
        return self._results_map.get(key, self._results_map.get(query, []))[:limit]


class FakePeopleResolver:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, identifier: str):
        return self._mapping.get(identifier)


class FakeNameIndex:
    def __init__(self, mapping):
        self._mapping = mapping
        self._by_stem = {
            stem: SimpleNamespace(path=path)
            for stem, path in mapping.values()
        }

    def match(self, candidate: str):
        resolved = self._mapping.get(candidate)
        return resolved[0] if resolved else None


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.vault.root = tmp_path
    return settings


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.asyncio
async def test_build_meeting_context_reads_people_and_notes(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(briefing, "get_settings", lambda: settings)

    kang = tmp_path / "1.INPUT/People/강준서_더해커톤.md"
    lee = tmp_path / "1.INPUT/People/이보영_워크모어.md"
    meeting_note = tmp_path / "1.INPUT/Meeting/2026-04-06_워크모어 갈등.md"
    inbox_note = tmp_path / "1.INPUT/Inbox/더해커톤-워크모어.md"

    _write(kang, "# 강준서\n더해커톤 운영 측 핵심 인물")
    _write(lee, "# 이보영\n워크모어 측 실무 창구")
    _write(meeting_note, "# 워크모어 갈등\n강준서와 이보영 사이의 갈등 봉합이 핵심이다.")
    _write(inbox_note, "# 최근 대화\n더해커톤과 워크모어의 긴장을 정리해야 한다.")

    name_index = FakeNameIndex({
        "kang joonseo": ("강준서_더해커톤", kang),
        "강준서": ("강준서_더해커톤", kang),
        "lee boyoung": ("이보영_워크모어", lee),
        "이보영": ("이보영_워크모어", lee),
    })
    people_resolver = FakePeopleResolver({
        "kang.joonseo@example.com": "강준서_더해커톤",
        "kang joonseo": "강준서_더해커톤",
        "lee.boyoung@example.com": "이보영_워크모어",
        "lee boyoung": "이보영_워크모어",
    })
    search = FakeSearch({
        "워크모어 해결": [
            {
                "path": "1.INPUT/Meeting/2026-04-06_워크모어 갈등.md",
                "title": "2026-04-06_워크모어 갈등",
                "snippet": "강준서 ... 이보영 ... 갈등 봉합",
            },
        ],
        "워크모어 해결 강준서": [
            {
                "path": "1.INPUT/Inbox/더해커톤-워크모어.md",
                "title": "더해커톤-워크모어",
                "snippet": "긴장을 정리해야 한다",
            },
        ],
    })

    context = await briefing.build_meeting_context(
        {
            "summary": "워크모어 해결",
            "start": "2026-04-09T19:00:00+09:00",
            "attendees": [
                "kang.joonseo@example.com",
                "lee.boyoung@example.com",
            ],
        },
        vault_search=search,
        name_index=name_index,
        people_resolver=people_resolver,
    )

    assert [person.display_name for person in context.attendees] == ["강준서", "이보영"]
    assert context.attendees[0].tags == ["더해커톤"]
    assert context.attendees[1].tags == ["워크모어"]
    assert len(context.evidence_notes) >= 2
    assert context.evidence_notes[0].title in {
        "2026-04-06_워크모어 갈등",
        "더해커톤-워크모어",
    }
    assert "갈등 봉합" in "\n".join(note.excerpt for note in context.evidence_notes)


@pytest.mark.asyncio
async def test_compose_meeting_brief_uses_llm_output_without_leaking_snippets(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(briefing, "get_settings", lambda: settings)

    kang = tmp_path / "1.INPUT/People/강준서_더해커톤.md"
    evidence = tmp_path / "1.INPUT/Meeting/2026-04-06_워크모어 갈등.md"
    _write(kang, "# 강준서\n더해커톤 운영 측")
    _write(evidence, "# 워크모어 갈등\n강준서와 이보영 갈등을 봉합해야 한다.")

    name_index = FakeNameIndex({
        "강준서": ("강준서_더해커톤", kang),
        "kang joonseo": ("강준서_더해커톤", kang),
    })
    people_resolver = FakePeopleResolver({
        "kang.joonseo@example.com": "강준서_더해커톤",
        "kang joonseo": "강준서_더해커톤",
    })
    search = FakeSearch({
        "워크모어 해결": [
            {
                "path": "1.INPUT/Meeting/2026-04-06_워크모어 갈등.md",
                "title": "2026-04-06_워크모어 갈등",
                "snippet": "→강준서← 와 [[이보영]] 갈등 봉합",
            },
        ],
    })

    async def fake_call_llm(prompt: str, *, max_tokens: int = 2048, caller: str = "") -> str:
        assert "2026-04-06_워크모어 갈등" in prompt
        return """
        {
          "situation": "강준서-이보영 갈등을 중심으로 더해커톤-워크모어 긴장을 봉합하는 미팅입니다.",
          "why_now": "오늘 미팅에서 최소 합의선을 못 만들면 후속 커뮤니케이션이 더 꼬일 수 있습니다.",
          "direct_people": [{"name": "강준서", "role": "더해커톤 측", "relevance": "직접 당사자"}],
          "background_people": [{"name": "Adam Kim", "relevance": "과거 연결은 있으나 이번 건의 직접 당사자는 아님"}],
          "timeline": ["최근 노트에서 갈등 봉합이 핵심 쟁점으로 반복 확인됨"],
          "advice": ["양측 민감 포인트를 먼저 분리해서 확인하세요."],
          "questions": ["오늘 반드시 합의해야 하는 최소선은 무엇인가"],
          "confidence": "medium"
        }
        """

    monkeypatch.setattr(briefing, "call_llm", fake_call_llm)

    text = await briefing.compose_meeting_brief(
        {
            "summary": "워크모어 해결",
            "start": "2026-04-09T19:00:00+09:00",
            "attendees": ["kang.joonseo@example.com"],
        },
        vault_search=search,
        name_index=name_index,
        people_resolver=people_resolver,
    )

    assert "19:00 워크모어 해결" in text
    assert "강준서-이보영 갈등" in text
    assert "양측 민감 포인트" in text
    assert "→" not in text
    assert "[[" not in text
    assert "1.INPUT/Meeting" not in text
