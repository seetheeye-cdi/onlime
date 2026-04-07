"""Click CLI for Onlime.

Commands:
    onlime run [--only gcal,plaud] [--date] [--dry-run]
    onlime daily [--date] [--dry-run]
    onlime status
    onlime setup gcal
    onlime setup plaud
    onlime migrate
"""
from __future__ import annotations

import logging
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import click

from onlime.config import get_settings


def setup_logging(verbose: bool = False) -> None:
    """Configure logging to both console and file."""
    settings = get_settings()
    settings.state.resolved_dir.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(str(settings.state.log_file), encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)


def notify_error(message: str) -> None:
    """Send macOS notification on error."""
    try:
        subprocess.run([
            'osascript', '-e',
            f'display notification "{message}" with title "Onlime 오류"'
        ], capture_output=True, timeout=5)
    except Exception:
        pass


@click.group()
@click.version_option(package_name="onlime")
def cli():
    """Onlime — Personal AI workflow system for Obsidian."""
    pass


@cli.command()
@click.option('--only', type=str, default=None, help='커넥터 선택 (gcal,plaud,daily)')
@click.option('--date', 'target_date', type=str, default=None, help='대상 날짜 (YYYY-MM-DD)')
@click.option('--gcal-json', type=click.Path(exists=True), default=None, help='JSON 파일에서 캘린더 이벤트 읽기')
@click.option('--days', type=int, default=7, help='최근 N일 녹음만 처리 (기본: 7)')
@click.option('--dry-run', is_flag=True, help='미리보기 (파일 변경 없음)')
@click.option('--verbose', '-v', is_flag=True, help='상세 로그')
def run(only, target_date, gcal_json, days, dry_run, verbose):
    """동기화 실행."""
    setup_logging(verbose)

    from onlime.engine import run_sync

    only_list = [s.strip() for s in only.split(',')] if only else None
    td = datetime.strptime(target_date, '%Y-%m-%d').date() if target_date else None

    try:
        run_sync(
            only=only_list,
            target_date=td,
            gcal_json=gcal_json,
            days=days,
            dry_run=dry_run,
        )
    except Exception as e:
        notify_error(str(e))
        sys.exit(1)


@cli.command()
@click.option('--date', 'target_date', type=str, default=None, help='대상 날짜 (YYYY-MM-DD, 기본: 오늘)')
@click.option('--dry-run', is_flag=True, help='미리보기 (파일 변경 없음)')
@click.option('--verbose', '-v', is_flag=True, help='상세 로그')
def daily(target_date, dry_run, verbose):
    """오늘의 Plaud 녹음을 요약하여 데일리 노트에 삽입."""
    setup_logging(verbose)

    from onlime.outputs.daily_summary import inject_daily_summary

    td = datetime.strptime(target_date, '%Y-%m-%d').date() if target_date else None

    try:
        inject_daily_summary(target_date=td, dry_run=dry_run)
    except Exception as e:
        notify_error(str(e))
        raise


@cli.command()
def status():
    """동기화 상태 확인."""
    import json
    settings = get_settings()
    state_file = settings.state.state_file

    if not state_file.exists():
        click.echo("상태 파일 없음. 아직 동기화가 실행되지 않았습니다.")
        return

    data = json.loads(state_file.read_text(encoding='utf-8'))
    connectors = data.get("connectors", {})

    click.echo(f"상태 파일: {state_file}")
    click.echo(f"스키마 버전: {data.get('schema_version', '?')}")
    click.echo()

    for name, info in connectors.items():
        last_sync = info.get("last_sync", "없음")
        processed_count = len(info.get("processed", {}))
        click.echo(f"[{name}]")
        click.echo(f"  마지막 동기화: {last_sync}")
        click.echo(f"  처리된 항목: {processed_count}개")
        click.echo()

    # Check connector availability
    from onlime.connectors.registry import load_all, list_connectors, get_connector
    load_all()
    click.echo("커넥터 상태:")
    for name in list_connectors():
        conn = get_connector(name)
        status_str = "사용 가능" if conn.is_available() else "설정 필요"
        click.echo(f"  {name}: {status_str}")


@cli.group()
def setup():
    """커넥터 초기 설정."""
    pass


@setup.command('gcal')
def setup_gcal():
    """Google Calendar OAuth2 설정."""
    settings = get_settings()
    settings.state.resolved_dir.mkdir(parents=True, exist_ok=True)

    creds_file = settings.gcal.resolved_creds_file
    token_file = settings.gcal.resolved_token_file

    click.echo("=" * 50)
    click.echo("Google Calendar OAuth2 Setup")
    click.echo("=" * 50)

    if not creds_file.exists():
        click.echo(f"""
[Step 1] credentials.json이 필요합니다.

1. https://console.cloud.google.com/ 접속
2. 프로젝트 생성 또는 선택
3. API 및 서비스 → 라이브러리 → "Google Calendar API" 검색 → 사용 설정
4. API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기
   → OAuth 클라이언트 ID → 데스크톱 앱
5. JSON 다운로드 후 아래 경로에 저장:
   {creds_file}
""")
        click.pause("credentials.json을 저장한 후 Enter를 누르세요...")

        if not creds_file.exists():
            click.echo(f"  {creds_file} 파일을 찾을 수 없습니다.")
            sys.exit(1)

    click.echo("\n[Step 2] 브라우저에서 Google 계정 인증...")

    from google_auth_oauthlib.flow import InstalledAppFlow
    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    click.echo(f"\n  인증 완료! 토큰 저장됨: {token_file}")


@setup.command('plaud')
@click.option('--token', type=str, default=None, help='수동으로 토큰 입력 (bearer eyJ...)')
def setup_plaud(token):
    """Plaud.ai 토큰 설정."""
    import json
    import urllib.request

    settings = get_settings()
    settings.state.resolved_dir.mkdir(parents=True, exist_ok=True)

    token_file = settings.plaud.token_file.expanduser()
    plaud_config = settings.plaud.plaud_config_file.expanduser()

    # Detect API domain
    app_config = Path.home() / 'Library' / 'Application Support' / 'Plaud' / 'config.json'
    if app_config.exists():
        cfg = json.loads(app_config.read_text())
        api_domain = cfg.get('apiDomain', settings.plaud.api_base)
    else:
        api_domain = settings.plaud.api_base

    click.echo(f'API 도메인: {api_domain}')

    def test_token(t):
        req = urllib.request.Request(
            f'{api_domain}/file/simple/web?page=1&pageSize=1',
            headers={'Authorization': f'bearer {t}', 'Content-Type': 'application/json'},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.status == 200
        except Exception:
            return False

    # Check existing token
    if token_file.exists() and not token:
        existing = token_file.read_text().strip()
        if test_token(existing):
            click.echo(f'기존 토큰이 유효합니다: {token_file}')
            return
        click.echo('기존 토큰이 만료되었습니다. 새 토큰이 필요합니다.')

    if token:
        t = token.strip()
        if t.lower().startswith('bearer '):
            t = t[7:]
        if test_token(t):
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(t)
            plaud_config.write_text(json.dumps({'token': t, 'api_domain': api_domain}, indent=2))
            click.echo('토큰이 유효합니다!')
        else:
            click.echo('토큰이 유효하지 않습니다.')
            sys.exit(1)
        return

    # Interactive mode
    click.echo()
    click.echo('=' * 50)
    click.echo('Plaud.ai 토큰을 가져오는 방법:')
    click.echo('=' * 50)
    click.echo()
    click.echo('1. Chrome에서 https://web.plaud.ai 접속 (로그인 상태)')
    click.echo('2. F12 키 → Console 탭 열기')
    click.echo('3. 아래 코드를 Console에 붙여넣고 Enter:')
    click.echo()
    click.echo('   localStorage.getItem("tokenstr")')
    click.echo()
    click.echo('4. 출력된 "bearer eyJ..." 값을 복사')
    click.echo()

    token_input = click.prompt('토큰을 여기에 붙여넣기 (bearer eyJ...)')

    t = token_input.strip()
    if t.startswith('"') and t.endswith('"'):
        t = t[1:-1]
    if t.lower().startswith('bearer '):
        t = t[7:]

    if test_token(t):
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(t)
        plaud_config.write_text(json.dumps({'token': t, 'api_domain': api_domain}, indent=2))
        click.echo('토큰이 유효합니다! Plaud 동기화를 사용할 수 있습니다.')
    else:
        click.echo('토큰이 유효하지 않습니다. 다시 시도해주세요.')
        sys.exit(1)


@cli.group()
def recording():
    """폰 녹음 동기화 관리."""
    pass


@recording.command('list')
@click.option('--verbose', '-v', is_flag=True, help='상세 로그')
def recording_list(verbose):
    """동기화된 녹음 파일 목록."""
    setup_logging(verbose)

    from onlime.connectors.registry import load_all, get_connector

    load_all()
    conn = get_connector("recording_sync")

    if not conn.is_available():
        click.echo("recording_sync가 비활성화 상태입니다. onlime.toml에서 enabled = true로 설정하세요.")
        return

    results = conn.fetch()
    if not results:
        click.echo("동기화된 녹음 파일이 없습니다.")
        return

    from onlime.state.store import SyncState
    settings = get_settings()
    state = SyncState(settings.state.state_file)

    click.echo(f"동기화된 녹음: {len(results)}개\n")
    for r in results:
        processed = state.is_processed("recording_sync", r.source_id)
        status = "처리됨" if processed else "미처리"
        duration = f"{int(r.duration_minutes)}분" if r.duration_minutes else "?"
        size_mb = r.metadata.get("file_size", 0) / 1_048_576
        click.echo(f"  [{status}] {r.title}")
        click.echo(f"         {r.timestamp.strftime('%Y-%m-%d %H:%M')} | {duration} | {size_mb:.1f}MB")


@recording.command('process')
@click.option('--dry-run', is_flag=True, help='미리보기 (파일 변경 없음)')
@click.option('--verbose', '-v', is_flag=True, help='상세 로그')
def recording_process(dry_run, verbose):
    """미처리 녹음 수동 처리 (노트 생성)."""
    setup_logging(verbose)

    from onlime.connectors.registry import load_all, get_connector
    from onlime.outputs.recording_note import create_recording_note
    from onlime.state.store import SyncState

    settings = get_settings()
    load_all()
    conn = get_connector("recording_sync")

    if not conn.is_available():
        click.echo("recording_sync가 비활성화 상태입니다.")
        return

    state = SyncState(settings.state.state_file)
    results = conn.fetch()
    new_count = 0

    for r in results:
        if not state.is_processed("recording_sync", r.source_id):
            note_path = create_recording_note(r, dry_run=dry_run)
            if not dry_run:
                state.mark_processed("recording_sync", r.source_id, note_path=str(note_path))
            new_count += 1

    if not dry_run and new_count:
        state.update_last_sync("recording_sync")
        state.save()

    click.echo(f"{'[DRY-RUN] ' if dry_run else ''}처리 완료: {new_count}개 녹음 노트 생성")


@recording.command('watch')
@click.option('--verbose', '-v', is_flag=True, help='상세 로그')
def recording_watch(verbose):
    """실시간 녹음 폴더 감시 (watchdog)."""
    setup_logging(verbose)
    import time

    settings = get_settings()
    watch_dir = settings.recording_sync.resolved_watch_dir
    extensions = set(settings.recording_sync.extensions)

    if not watch_dir.is_dir():
        click.echo(f"감시 폴더가 없습니다: {watch_dir}")
        return

    click.echo(f"녹음 폴더 감시 시작: {watch_dir}")
    click.echo("새 파일 감지 시 자동 처리합니다. Ctrl+C로 종료.")

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class RecordingHandler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                fpath = Path(event.src_path)
                if fpath.suffix.lower() not in extensions:
                    return

                click.echo(f"\n새 녹음 감지: {fpath.name}")
                # Brief delay for file write completion
                time.sleep(2)

                from onlime.connectors.recording_sync import _file_to_connector_result
                from onlime.outputs.recording_note import create_recording_note
                from onlime.state.store import SyncState

                try:
                    result = _file_to_connector_result(fpath)
                    state = SyncState(settings.state.state_file)
                    if not state.is_processed("recording_sync", result.source_id):
                        note_path = create_recording_note(result)
                        state.mark_processed("recording_sync", result.source_id, note_path=str(note_path))
                        state.save()
                        click.echo(f"  노트 생성 완료: {note_path.name}")
                except Exception as e:
                    click.echo(f"  처리 실패: {e}")

        observer = Observer()
        observer.schedule(RecordingHandler(), str(watch_dir), recursive=True)
        observer.start()

        while True:
            time.sleep(1)

    except ImportError:
        click.echo("watchdog 패키지가 필요합니다: pip install watchdog")
        click.echo("대신 폴링 모드로 실행합니다...")

        from onlime.connectors.registry import load_all, get_connector
        from onlime.outputs.recording_note import create_recording_note
        from onlime.state.store import SyncState

        load_all()
        conn = get_connector("recording_sync")
        processed_ids: set[str] = set()

        while True:
            state = SyncState(settings.state.state_file)
            results = conn.fetch()
            for r in results:
                if r.source_id not in processed_ids and not state.is_processed("recording_sync", r.source_id):
                    click.echo(f"\n새 녹음 발견: {r.title}")
                    note_path = create_recording_note(r)
                    state.mark_processed("recording_sync", r.source_id, note_path=str(note_path))
                    state.save()
                    processed_ids.add(r.source_id)
                    click.echo(f"  노트 생성 완료: {note_path.name}")
            time.sleep(10)

    except KeyboardInterrupt:
        click.echo("\n감시 종료.")


@cli.command()
def migrate():
    """기존 obsidian-sync 데이터를 마이그레이션."""
    from onlime.state.migration import migrate_state, migrate_auth_files

    settings = get_settings()
    old_dir = Path.home() / ".config" / "obsidian-sync"
    new_dir = settings.state.resolved_dir

    click.echo(f"마이그레이션: {old_dir} → {new_dir}")

    # Migrate auth files
    migrated = migrate_auth_files(old_dir, new_dir)
    if migrated:
        click.echo(f"  인증 파일 복사: {', '.join(migrated)}")
    else:
        click.echo("  인증 파일: 복사할 파일 없음")

    # Migrate state
    old_state = old_dir / "state.json"
    new_state = settings.state.state_file
    if migrate_state(old_state, new_state):
        click.echo(f"  상태 파일 마이그레이션 완료: {new_state}")
    else:
        click.echo("  상태 파일: 마이그레이션 불필요")

    click.echo("완료!")
