"""Neo4j 書き込みをバックグラウンドで集約するユーティリティ。"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from idea_graph.ingestion.extractor import ExtractedInfo
from idea_graph.ingestion.graph_writer import GraphWriterService

logger = logging.getLogger(__name__)

WriteCallback = Callable[[Exception | None], None]


@dataclass
class _WriteItem:
    paper_id: str
    published_date: datetime | None
    extracted: ExtractedInfo | None
    on_done: WriteCallback | None = None


@dataclass
class _FlushRequest:
    done_event: threading.Event


@dataclass
class _StopRequest:
    done_event: threading.Event


class BufferedGraphWriter:
    """GraphWriterService への細かい書き込みをまとめて flush する。"""

    def __init__(
        self,
        writer: GraphWriterService,
        extraction_batch_size: int = 8,
        published_date_batch_size: int = 32,
        flush_interval_seconds: float = 1.0,
    ) -> None:
        self.writer = writer
        self.extraction_batch_size = max(1, extraction_batch_size)
        self.published_date_batch_size = max(1, published_date_batch_size)
        self.flush_interval_seconds = max(0.0, flush_interval_seconds)

        self._queue: queue.Queue[_WriteItem | _FlushRequest | _StopRequest] = queue.Queue()
        self._fatal_error: Exception | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="buffered-graph-writer",
            daemon=True,
        )
        self._thread.start()

    def enqueue_published_date(
        self,
        paper_id: str,
        published_date: datetime | None,
        on_done: WriteCallback | None = None,
    ) -> None:
        if published_date is None:
            if on_done is not None:
                on_done(None)
            return
        self._enqueue(
            _WriteItem(
                paper_id=paper_id,
                published_date=published_date,
                extracted=None,
                on_done=on_done,
            )
        )

    def enqueue_extracted(
        self,
        extracted: ExtractedInfo,
        published_date: datetime | None = None,
        on_done: WriteCallback | None = None,
    ) -> None:
        self._enqueue(
            _WriteItem(
                paper_id=extracted.paper_id,
                published_date=published_date,
                extracted=extracted,
                on_done=on_done,
            )
        )

    def flush(self) -> None:
        self._raise_if_failed()
        done_event = threading.Event()
        self._queue.put(_FlushRequest(done_event))
        done_event.wait()
        self._raise_if_failed()

    def close(self) -> None:
        if self._closed:
            self._raise_if_failed()
            return
        done_event = threading.Event()
        self._queue.put(_StopRequest(done_event))
        done_event.wait()
        self._thread.join()
        self._closed = True
        self._raise_if_failed()

    def _enqueue(self, item: _WriteItem) -> None:
        if self._closed:
            raise RuntimeError("BufferedGraphWriter is already closed")
        self._raise_if_failed()
        self._queue.put(item)

    def _raise_if_failed(self) -> None:
        if self._fatal_error is not None:
            raise RuntimeError("BufferedGraphWriter failed") from self._fatal_error

    def _run(self) -> None:
        batch: list[_WriteItem] = []
        deadline: float | None = None

        while True:
            timeout = None
            if batch and deadline is not None:
                timeout = max(0.0, deadline - time.monotonic())

            try:
                command = self._queue.get(timeout=timeout)
            except queue.Empty:
                self._flush_batch(batch)
                batch = []
                deadline = None
                continue

            if isinstance(command, _WriteItem):
                if self._fatal_error is not None:
                    self._finalize_item(command, self._fatal_error)
                    continue

                batch.append(command)
                if deadline is None:
                    deadline = time.monotonic() + self.flush_interval_seconds
                if self._should_flush(batch):
                    self._flush_batch(batch)
                    batch = []
                    deadline = None
                continue

            if isinstance(command, _FlushRequest):
                self._flush_batch(batch)
                batch = []
                deadline = None
                command.done_event.set()
                continue

            self._flush_batch(batch)
            batch = []
            command.done_event.set()
            return

    def _should_flush(self, batch: list[_WriteItem]) -> bool:
        extraction_count = sum(1 for item in batch if item.extracted is not None)
        published_date_count = sum(1 for item in batch if item.published_date is not None)
        return (
            extraction_count >= self.extraction_batch_size
            or published_date_count >= self.published_date_batch_size
        )

    def _flush_batch(self, batch: list[_WriteItem]) -> None:
        if not batch:
            return

        published_updates = [
            (item.paper_id, item.published_date)
            for item in batch
            if item.published_date is not None
        ]
        extractions = [item.extracted for item in batch if item.extracted is not None]

        error: Exception | None = None
        try:
            if self._fatal_error is not None:
                raise self._fatal_error
            if published_updates:
                self.writer.update_paper_published_dates(published_updates)
            if extractions:
                self.writer.write_extracted_batch(extractions)
        except Exception as exc:
            error = exc
            if self._fatal_error is None:
                self._fatal_error = exc
                logger.exception("Buffered graph writer failed")

        for item in batch:
            self._finalize_item(item, error)

    @staticmethod
    def _finalize_item(item: _WriteItem, error: Exception | None) -> None:
        if item.on_done is not None:
            item.on_done(error)
