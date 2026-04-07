"""CLI entry point for Onlime."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import click

from onlime import setup_logging
from onlime.config import get_settings

_PID_FILE = Path("~/.onlime/onlime.pid").expanduser()


def _acquire_pid_lock() -> None:
    """Ensure only one daemon instance runs. Exit if another is alive."""
    if _PID_FILE.exists():
        try:
            old_pid = int(_PID_FILE.read_text().strip())
            # Check if process is still alive
            os.kill(old_pid, 0)
            click.echo(f"Onlime already running (PID {old_pid}). Exiting.")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass  # stale PID file, safe to overwrite
        except PermissionError:
            click.echo(f"Onlime already running (PID, permission denied). Exiting.")
            sys.exit(1)
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def _release_pid_lock() -> None:
    """Remove PID file on shutdown."""
    try:
        _PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


@click.group()
def cli() -> None:
    """Onlime — Personal AI Second Brain."""
    setup_logging(get_settings().general.log_level)


@cli.command()
def status() -> None:
    """Show system status."""
    settings = get_settings()
    db_path = settings.state.db_path

    click.echo("Onlime v2.0.0")
    click.echo(f"  Vault:  {settings.vault.root}")
    click.echo(f"  DB:     {db_path} ({'exists' if db_path.exists() else 'not created'})")
    click.echo(f"  Config: {settings.general.log_level} log level")


@cli.command()
def run() -> None:
    """Start the Onlime daemon."""
    _acquire_pid_lock()
    try:
        asyncio.run(_run())
    finally:
        _release_pid_lock()


async def _run() -> None:
    from onlime.engine import Engine
    from onlime.maintenance import GCalSyncTask, KakaoSync, VaultIndexTask, VaultJanitor
    from onlime.search.fts import VaultSearch
    from onlime.state.store import StateStore

    settings = get_settings()
    store = StateStore(settings.state.db_path)
    await store.open()

    engine = Engine(store)
    await engine.start()

    # === FTS5 search initialization ===
    vault_search = VaultSearch(store.db)
    await vault_search.ensure_schema()

    # === Background tasks (unified list) ===
    tasks: list = []

    # 1) Vault janitor (always)
    janitor = VaultJanitor(interval_seconds=1800, name_index=engine._name_index)
    try:
        await janitor.start(store)
        tasks.append(janitor)
        click.echo("Vault janitor started (every 30 min).")
    except Exception as exc:
        click.echo(f"Vault janitor failed to start: {exc}")

    # 2) KakaoSync (kakaocli mode)
    kakao_sync_running = False
    if settings.kakao.enabled and settings.kakao.use_kakaocli:
        kakao_sync = KakaoSync(
            interval_seconds=settings.kakao.poll_interval_minutes * 60,
        )
        try:
            await kakao_sync.start(store)
            tasks.append(kakao_sync)
            kakao_sync_running = True
            click.echo(f"KakaoTalk sync started (every "
                        f"{settings.kakao.poll_interval_minutes} min).")
        except Exception as exc:
            click.echo(f"KakaoTalk sync failed to start: {exc}")

    # 3) GDrive rescan (periodic catch-up for files missed during sleep)
    if settings.gdrive.enabled and settings.gdrive.watch_paths:
        from onlime.connectors.gdrive import GDriveRescanTask

        rescan = GDriveRescanTask(interval_seconds=1800, queue=engine.queue)
        try:
            await rescan.start(store)
            tasks.append(rescan)
            click.echo("GDrive rescan started (every 30 min).")
        except Exception as exc:
            click.echo(f"GDrive rescan failed to start: {exc}")

    # 4) GCal sync (when enabled)
    if settings.gcal.enabled:
        gcal_sync = GCalSyncTask(
            interval_seconds=settings.gcal.schedule_minutes * 60,
        )
        try:
            await gcal_sync.start(store)
            tasks.append(gcal_sync)
            click.echo(f"GCal sync started (every {settings.gcal.schedule_minutes} min).")
        except Exception as exc:
            click.echo(f"GCal sync failed to start: {exc}")

    # 5) Vault FTS5 indexer (always)
    vault_index = VaultIndexTask(interval_seconds=600, search=vault_search)
    try:
        await vault_index.start(store)
        tasks.append(vault_index)
        click.echo("Vault FTS5 indexer started (every 10 min).")
    except Exception as exc:
        click.echo(f"Vault FTS5 indexer failed to start: {exc}")

    # === Connectors ===
    connectors = []

    # Telegram bot
    if settings.telegram_bot.enabled:
        from onlime.connectors.telegram import TelegramConnector

        tg = TelegramConnector()
        try:
            await tg.start(engine.queue)
            engine.set_telegram_app(tg._app)
            tg.set_vault_search(vault_search)
            connectors.append(tg)
            click.echo("Telegram bot started.")
        except Exception as exc:
            click.echo(f"Telegram bot failed to start: {exc}")

    # GDrive watcher (real-time via watchdog)
    if settings.gdrive.enabled and settings.gdrive.watch_paths:
        from onlime.connectors.gdrive import GDriveConnector

        gdrive = GDriveConnector()
        try:
            await gdrive.start(engine.queue)
            connectors.append(gdrive)
            click.echo("GDrive watcher started.")
        except Exception as exc:
            click.echo(f"GDrive watcher failed to start: {exc}")

    # Slack poller
    if settings.slack.enabled:
        from onlime.connectors.slack import SlackConnector

        slack_conn = SlackConnector()
        try:
            await slack_conn.start(engine.queue)
            connectors.append(slack_conn)
            click.echo("Slack connector started.")
        except Exception as exc:
            click.echo(f"Slack connector failed: {exc}")

    # KakaoTalk .txt watcher (fallback for manual exports)
    if settings.kakao.enabled and settings.kakao.export_dir and not kakao_sync_running:
        from onlime.connectors.kakao import KakaoConnector

        kakao_conn = KakaoConnector()
        try:
            await kakao_conn.start(engine.queue)
            connectors.append(kakao_conn)
            click.echo("KakaoTalk watcher started.")
        except Exception as exc:
            click.echo(f"KakaoTalk watcher failed: {exc}")

    click.echo("Onlime running. Press Ctrl+C to stop.")

    # Graceful shutdown via signal
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    await shutdown_event.wait()

    # === Unified shutdown ===
    click.echo("\nShutting down...")
    for conn in reversed(connectors):
        await conn.stop()
    for t in reversed(tasks):
        await t.stop()
    await engine.stop()
    await store.close()
    click.echo("Onlime stopped.")


@cli.command()
def setup() -> None:
    """Initialize config and data directories."""
    settings = get_settings()
    state_dir = settings.state.dir.expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "logs").mkdir(exist_ok=True)

    vault_root = settings.vault.root.expanduser()
    if vault_root.exists():
        for subdir in [
            settings.vault.system_dir,
            settings.vault.inbox_dir,
            settings.vault.meeting_dir,
            settings.vault.article_dir,
            settings.vault.book_dir,
            settings.vault.class_dir,
            settings.vault.media_dir,
            settings.vault.term_dir,
            settings.vault.quote_dir,
            settings.vault.people_dir,
            settings.vault.recording_dir,
            settings.vault.input_archive_dir,
            settings.vault.daily_dir,
            settings.vault.weekly_dir,
            settings.vault.monthly_dir,
            settings.vault.project_dir,
            settings.vault.explore_dir,
            settings.vault.think_dir,
            settings.vault.questions_dir,
            settings.vault.output_people_dir,
            settings.vault.wiki_dir,
            settings.vault.archive_dir,
        ]:
            (vault_root / subdir).mkdir(parents=True, exist_ok=True)
        click.echo(f"Vault directories created in {vault_root}")
    else:
        click.echo(f"Vault root not found: {vault_root}")

    click.echo(f"Data directory: {state_dir}")
    click.echo("Setup complete.")
