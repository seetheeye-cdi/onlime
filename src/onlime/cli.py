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
    from onlime.maintenance import ClaudeSessionSync, EventRetryTask, GCalSyncTask, GraphIndexTask, KakaoSync, SchedulerTask, TelegramGroupDigestTask, VaultIndexTask, VaultJanitor
    from onlime.maintenance.meeting_brief import MeetingBriefTask
    from onlime.search.fts import VaultSearch
    from onlime.state.store import StateStore

    settings = get_settings()
    store = StateStore(settings.state.db_path)
    await store.open()

    engine = Engine(store)
    await engine.start()

    vault_search = VaultSearch(store.db)
    await vault_search.ensure_schema()

    # Semantic search (graceful: skip if Ollama unavailable)
    semantic_search = None
    hybrid_search = None
    if settings.search.use_semantic:
        from onlime.search.semantic import SemanticSearch
        semantic_search = SemanticSearch()
        if await semantic_search.check_available():
            click.echo("Semantic search (Ollama) available.")
        else:
            click.echo("Semantic search unavailable (Ollama not running). FTS5 only.")
            semantic_search = None

    from onlime.search.graph import VaultGraph
    from onlime.search.hybrid import HybridSearch
    hybrid_search = HybridSearch(vault_search, semantic_search)

    vault_graph = VaultGraph(store.db, engine._name_index)
    await vault_graph.ensure_schema()

    # === Background tasks — declarative list ===
    _bg_tasks: list[tuple[str, object, bool]] = [
        # (label, instance, enabled)
        (
            "Vault janitor (every 30 min)",
            VaultJanitor(interval_seconds=1800, name_index=engine._name_index),
            True,
        ),
        (
            f"KakaoTalk sync (every {settings.kakao.poll_interval_minutes} min)",
            KakaoSync(interval_seconds=settings.kakao.poll_interval_minutes * 60),
            settings.kakao.enabled and settings.kakao.use_kakaocli,
        ),
        (
            "GCal sync (every {0} min)".format(settings.gcal.schedule_minutes),
            GCalSyncTask(interval_seconds=settings.gcal.schedule_minutes * 60),
            settings.gcal.enabled,
        ),
        (
            "Vault indexer (every 10 min, FTS5 + semantic)",
            VaultIndexTask(interval_seconds=600, search=vault_search, semantic=semantic_search),
            True,
        ),
        (
            "Graph indexer (every 10 min, wikilinks)",
            GraphIndexTask(interval_seconds=600, graph=vault_graph),
            True,
        ),
        (
            "Claude session sync (every 15 min)",
            ClaudeSessionSync(interval_seconds=900, db=store.db),
            True,
        ),
        (
            "Event retry (every 5 min)",
            EventRetryTask(interval_seconds=300, engine_queue=engine.queue),
            True,
        ),
        (
            "Scheduler (brief/summary, every 5 min check)",
            SchedulerTask(interval_seconds=300),
            settings.scheduler.enabled,
        ),
        (
            "Meeting brief (every 5 min check)",
            MeetingBriefTask(interval_seconds=300),
            settings.gcal.enabled,
        ),
        (
            "Telegram group digest (every {} min)".format(
                settings.telegram_bot.group_digest_interval_minutes
            ),
            TelegramGroupDigestTask(
                interval_seconds=settings.telegram_bot.group_digest_interval_minutes * 60,
                group_ids=settings.telegram_bot.allowed_group_ids,
            ),
            settings.telegram_bot.group_sync_enabled,
        ),
    ]

    # GDrive rescan needs engine.queue — conditional import
    if settings.gdrive.enabled and settings.gdrive.watch_paths:
        from onlime.connectors.gdrive import GDriveRescanTask
        _bg_tasks.insert(2, (
            "GDrive rescan (every 30 min)",
            GDriveRescanTask(interval_seconds=1800, queue=engine.queue),
            True,
        ))

    tasks: list = []
    kakao_sync_running = False
    for label, task_obj, enabled in _bg_tasks:
        if not enabled:
            continue
        try:
            await task_obj.start(store)
            tasks.append(task_obj)
            if "KakaoTalk sync" in label:
                kakao_sync_running = True
            click.echo(f"{label} started.")
        except Exception as exc:
            click.echo(f"{label} failed to start: {exc}")

    # === Connectors — declarative list ===
    _conn_defs: list[tuple[str, str, str, bool]] = [
        # (label, module_path, class_name, enabled)
        ("Telegram bot", "onlime.connectors.telegram", "TelegramConnector",
         settings.telegram_bot.enabled),
        ("GDrive watcher", "onlime.connectors.gdrive", "GDriveConnector",
         settings.gdrive.enabled and bool(settings.gdrive.watch_paths)),
        ("Slack connector", "onlime.connectors.slack", "SlackConnector",
         settings.slack.enabled),
    ]

    connectors = []
    for label, mod_path, cls_name, enabled in _conn_defs:
        if not enabled:
            continue
        try:
            import importlib
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            conn = cls()
            await conn.start(engine.queue)
            connectors.append(conn)
            # Telegram-specific wiring
            if cls_name == "TelegramConnector":
                engine.set_telegram_app(conn._app)
                conn.set_vault_search(hybrid_search)
                conn.set_vault_graph(vault_graph)
                conn.set_store(store)
                # Inject Telegram app + dependencies into background tasks
                for t in tasks:
                    if hasattr(t, "set_telegram_app"):
                        t.set_telegram_app(conn._app)
                    if hasattr(t, "set_name_index"):
                        t.set_name_index(engine._name_index)
                    if hasattr(t, "set_vault_search"):
                        t.set_vault_search(hybrid_search)
                    if hasattr(t, "set_vault_graph"):
                        t.set_vault_graph(vault_graph)
            click.echo(f"{label} started.")
        except Exception as exc:
            click.echo(f"{label} failed to start: {exc}")

    # KakaoTalk .txt watcher (fallback for manual exports)
    if settings.kakao.enabled and settings.kakao.export_dir and not kakao_sync_running:
        try:
            from onlime.connectors.kakao import KakaoConnector
            kakao_conn = KakaoConnector()
            await kakao_conn.start(engine.queue)
            connectors.append(kakao_conn)
            click.echo("KakaoTalk watcher started.")
        except Exception as exc:
            click.echo(f"KakaoTalk watcher failed to start: {exc}")

    click.echo("Onlime running. Press Ctrl+C to stop.")

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    await shutdown_event.wait()

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
