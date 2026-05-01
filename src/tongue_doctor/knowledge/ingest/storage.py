"""Local-disk corpus storage.

Layout::

    knowledge/_local/
    ├── MANIFEST.json                    # global index of available sources
    └── <source>/
        ├── raw/                          # original artefacts (gitignored)
        ├── chunks.jsonl                  # one Chunk per line
        └── manifest.json                 # IngestionManifest for this source

The runtime reads ``chunks.jsonl`` directly to build BM25 / dense indices in a
later step. This module only owns disk layout and serialisation — no embedding,
no indexing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

from tongue_doctor.knowledge.schema import Chunk, IngestionManifest


class LocalCorpusStore:
    """Filesystem-backed store for ingested corpora.

    Intentionally thin: the only writes are append-on-open ``chunks.jsonl`` and a
    small JSON manifest. No locking — assumed single-writer per source (the
    ingester CLI).
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def source_dir(self, source: str) -> Path:
        d = self.root / source
        d.mkdir(parents=True, exist_ok=True)
        (d / "raw").mkdir(exist_ok=True)
        return d

    def chunks_path(self, source: str) -> Path:
        return self.source_dir(source) / "chunks.jsonl"

    def manifest_path(self, source: str) -> Path:
        return self.source_dir(source) / "manifest.json"

    def write_chunks(self, source: str, chunks: Iterable[Chunk]) -> int:
        path = self.chunks_path(source)
        seen: set[str] = set()
        count = 0
        with path.open("w", encoding="utf-8") as f:
            for chunk in chunks:
                if chunk.chunk_id in seen:
                    continue
                seen.add(chunk.chunk_id)
                f.write(chunk.model_dump_json() + "\n")
                count += 1
        return count

    def read_chunks(self, source: str) -> Iterator[Chunk]:
        path = self.chunks_path(source)
        if not path.is_file():
            return
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield Chunk.model_validate_json(line)

    def write_manifest(self, manifest: IngestionManifest) -> None:
        path = self.manifest_path(manifest.source)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        self._refresh_global_manifest()

    def _refresh_global_manifest(self) -> None:
        sources: list[dict[str, object]] = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            mpath = child / "manifest.json"
            if not mpath.is_file():
                continue
            sources.append(json.loads(mpath.read_text(encoding="utf-8")))
        global_manifest = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "sources": sources,
        }
        (self.root / "MANIFEST.json").write_text(
            json.dumps(global_manifest, indent=2, default=str), encoding="utf-8"
        )
