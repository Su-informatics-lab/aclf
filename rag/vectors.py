"""Patient note retrieval with optional vectors and a provenance-safe fallback."""

from __future__ import annotations

import csv
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "and", "are", "for", "from", "in", "is", "of", "on", "or",
    "patient", "the", "this", "to", "with",
}
_embedder = None


def _get_embedder(model_name: str):
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(model_name, trust_remote_code=True)
    return _embedder


class NoteStore:
    """Resolve report IDs to notes while preserving the full ID provenance chain."""

    def __init__(
        self,
        pid: int,
        mapping_path: Path,
        notes_dirs: list[Path],
        *,
        note_dates_path: Path | None = None,
        vectors_dir: Path | None = None,
        embed_model: str = "nomic-ai/nomic-embed-text-v1.5",
    ):
        self.pid = str(pid)
        self.mapping_path = Path(mapping_path)
        self.notes_dirs = [Path(path) for path in notes_dirs]
        self.note_dates_path = Path(note_dates_path) if note_dates_path else None
        self.vectors_dir = Path(vectors_dir) if vectors_dir else None
        self.embed_model = embed_model
        self._records: list[dict[str, Any]] | None = None
        self._vectors = None

    def _load_dates(self) -> dict[str, tuple[str, str]]:
        if not self.note_dates_path or not self.note_dates_path.exists():
            return {}
        with self.note_dates_path.open(encoding="utf-8-sig", newline="") as handle:
            return {
                row["report_id"].strip(): (
                    row.get("note_date", "").strip(),
                    row.get("source", "").strip(),
                )
                for row in csv.DictReader(handle)
                if row.get("report_id")
            }

    def _load_records(self) -> list[dict[str, Any]]:
        if self._records is not None:
            return self._records
        if not self.mapping_path.exists():
            raise FileNotFoundError(f"Report mapping not found: {self.mapping_path}")
        dates = self._load_dates()
        records: list[dict[str, Any]] = []
        with self.mapping_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                omop = row.get("OMOP_PERSON_ID", "").strip()
                if omop != self.pid:
                    continue
                report_id = row.get("REPORT_ID", "").strip()
                if not report_id:
                    continue
                note_path = next(
                    (directory / f"{report_id}.txt" for directory in self.notes_dirs
                     if (directory / f"{report_id}.txt").exists()),
                    None,
                )
                note_date, date_source = dates.get(report_id, ("", ""))
                records.append(
                    {
                        "omop_person_id": omop,
                        "global_patient_id": row.get("GLOBAL_PATIENT_ID", "").strip(),
                        "report_id": report_id,
                        "note_path": note_path,
                        "note_date": note_date or None,
                        "date_source": date_source or None,
                    }
                )
        self._records = records
        return records

    @staticmethod
    def _excerpt(text: str, terms: list[str], max_chars: int = 3500) -> str:
        lower = text.lower()
        positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
        center = min(positions) if positions else 0
        start = max(0, center - max_chars // 3)
        end = min(len(text), start + max_chars)
        prefix = "..." if start else ""
        suffix = "..." if end < len(text) else ""
        return prefix + text[start:end].strip() + suffix

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        date_start: str | None,
        date_end: str | None,
    ) -> list[dict[str, Any]]:
        terms = [token for token in _TOKEN_RE.findall(query.lower()) if token not in _STOP]
        if not terms:
            terms = _TOKEN_RE.findall(query.lower())
        scored: list[tuple[float, dict[str, Any], str]] = []
        for record in self._load_records():
            note_date = record["note_date"]
            if date_start or date_end:
                if not note_date:
                    continue
                if date_start and note_date < date_start:
                    continue
                if date_end and note_date > date_end:
                    continue
            path = record["note_path"]
            if path is None:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lower = text.lower()
            counts = Counter({term: lower.count(term) for term in terms})
            matched = sum(1 for term in terms if counts[term])
            if matched == 0:
                continue
            phrase_bonus = 3.0 if query.lower() in lower else 0.0
            score = matched * 5.0 + sum(min(counts[t], 5) for t in terms) + phrase_bonus
            scored.append((score, record, text))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "chunk_text": self._excerpt(text, terms),
                "score": score,
                "retrieval_method": "keyword",
                "omop_person_id": record["omop_person_id"],
                "global_patient_id": record["global_patient_id"],
                "report_id": record["report_id"],
                "note_date": record["note_date"],
                "date_source": record["date_source"],
                "source_directory": record["note_path"].parent.name,
            }
            for score, record, text in scored[:top_k]
        ]

    def _load_vectors(self):
        if self._vectors is not None:
            return self._vectors
        if not self.vectors_dir:
            return None
        path = self.vectors_dir / f"{self.pid}.npz"
        if not path.exists():
            return None
        import numpy as np

        self._vectors = np.load(path, allow_pickle=True)
        return self._vectors

    def search(
        self,
        query: str,
        top_k: int = 5,
        date_start: str | None = None,
        date_end: str | None = None,
    ) -> list[dict[str, Any]]:
        top_k = max(1, min(int(top_k), 20))
        data = self._load_vectors()
        if data is None:
            return self._keyword_search(query, top_k, date_start, date_end)

        import numpy as np

        chunks = list(data["chunks"])
        metadata = list(data["metadata"]) if "metadata" in data else [{}] * len(chunks)
        embeddings = data["embeddings"]
        q_vec = _get_embedder(self.embed_model).encode(query, normalize_embeddings=True)
        scores = embeddings @ q_vec
        results = []
        for idx in np.argsort(scores)[::-1]:
            meta = metadata[idx] if idx < len(metadata) else {}
            if not isinstance(meta, dict):
                meta = dict(meta)
            note_date = meta.get("note_date") or None
            if date_start or date_end:
                if not note_date:
                    continue
                if date_start and note_date < date_start:
                    continue
                if date_end and note_date > date_end:
                    continue
            results.append(
                {
                    "chunk_text": str(chunks[idx]),
                    "score": float(scores[idx]),
                    "retrieval_method": "semantic",
                    "omop_person_id": self.pid,
                    "global_patient_id": meta.get("global_patient_id"),
                    "report_id": meta.get("report_id"),
                    "note_date": note_date,
                    "date_source": meta.get("date_source"),
                }
            )
            if len(results) >= top_k:
                break
        return results

    def provenance_summary(self) -> dict[str, Any]:
        records = self._load_records()
        return {
            "omop_person_id": self.pid,
            "global_patient_ids": sorted(
                {r["global_patient_id"] for r in records if r["global_patient_id"]}
            ),
            "n_mapped_reports": len(records),
            "n_notes_found": sum(r["note_path"] is not None for r in records),
            "n_notes_with_dates": sum(bool(r["note_date"]) for r in records),
            "mapping_path": str(self.mapping_path),
            "note_directories": [str(path) for path in self.notes_dirs],
        }


__all__ = ["NoteStore"]
