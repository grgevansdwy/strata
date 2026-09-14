"""watchdog -> debounced per-file re-index callbacks on the asyncio loop."""

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from strata.indexer.repo_index import is_indexable

DEBOUNCE_S = 0.3


class RepoWatcher(FileSystemEventHandler):
    def __init__(self, root: Path, loop: asyncio.AbstractEventLoop, on_change: Callable[[set[str]], Awaitable[None]],
                 known_files: Callable[[], list[str]]):
        self.root = root.resolve()
        self.loop = loop
        self.on_change = on_change
        self.known_files = known_files
        self.pending: set[str] = set()
        self.timer: asyncio.TimerHandle | None = None
        self.observer = Observer()

    def start(self):
        self.observer.schedule(self, str(self.root), recursive=True)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join(timeout=2)

    def on_any_event(self, event: FileSystemEvent):  # watchdog thread
        if event.event_type in ("opened", "closed_no_write"):
            return
        rels = set()
        for p in (event.src_path, getattr(event, "dest_path", "")):
            if not p:
                continue
            try:
                rel = Path(p).resolve().relative_to(self.root).as_posix()
            except ValueError:
                continue
            if event.is_directory:
                # A deleted/moved directory may not emit events for the files inside it.
                rels.update(f for f in self.known_files() if f.startswith(rel + "/"))
            elif is_indexable(rel):
                rels.add(rel)
        if rels:
            self.loop.call_soon_threadsafe(self._schedule, rels)

    def _schedule(self, rels: set[str]):  # loop thread
        self.pending |= rels
        if self.timer:
            self.timer.cancel()
        self.timer = self.loop.call_later(DEBOUNCE_S, self._flush)

    def _flush(self):
        rels, self.pending = self.pending, set()
        asyncio.ensure_future(self.on_change(rels))
