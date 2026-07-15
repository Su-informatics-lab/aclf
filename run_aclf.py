#!/usr/bin/env python3
"""Run single-expert ACLF phenotyping over an OMOP-linked patient roster."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from agent import ACLFAgent
from config import ACLFConfig
from rag import PatientRAG
from scoring import score_aclf

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://catchat-api.msu.montana.edu/v1"
DEFAULT_MODEL = "gpt-oss:120b"


def normalize_api_base(value: str) -> str:
    value = value.rstrip("/")
    return value if value.endswith("/v1") else value + "/v1"


def load_api_key(explicit: str | None = None) -> str:
    key = explicit or os.environ.get("CATCHAT_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if key and key.strip():
        return key.strip()
    key_file = Path.home() / ".catchat_key"
    if key_file.exists() and key_file.read_text(encoding="utf-8").strip():
        return key_file.read_text(encoding="utf-8").strip()
    raise RuntimeError("Set CATCHAT_API_KEY/OPENAI_API_KEY or create ~/.catchat_key")


def load_patient_ids(path: Path) -> list[int]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        fields = rows.fieldnames or []
        column = next(
            (name for name in ("omop_person_id", "OMOP_PERSON_ID", "person_id") if name in fields),
            None,
        )
        if column is None:
            raise ValueError(f"No OMOP person ID column in {path}: {fields}")
        values = []
        for row in rows:
            value = (row.get(column) or "").strip()
            if value:
                values.append(int(value))
    return list(dict.fromkeys(values))


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


async def process_patient(
    pid: int,
    *,
    agent: ACLFAgent,
    args: argparse.Namespace,
) -> dict[str, Any]:
    sample_id = str(pid)
    output_path = args.output_dir / f"{sample_id}.json"
    if args.skip_existing and output_path.exists():
        return {"sample_id": sample_id, "status": "skipped", "path": str(output_path)}
    rag = PatientRAG(
        pid,
        ehr_db_path=args.ehr_db,
        mapping_path=args.mapping,
        notes_dirs=args.notes_dir,
        note_dates_path=args.note_dates,
        vectors_dir=args.vectors_dir,
        extraction_dir=args.extraction_dir,
    )
    try:
        provenance = rag.case_context()
        assessment = await agent.assess(rag=rag, sample_id=sample_id)
        payload = {
            "schema_version": "1.0",
            "sample_id": sample_id,
            "provenance": provenance,
            "assessment": assessment.model_dump(mode="json"),
            "scores": score_aclf(assessment),
            "run_metadata": {
                "model": args.model,
                "api_base": normalize_api_base(args.api_base),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        atomic_json(output_path, payload)
        error_path = args.output_dir / f"{sample_id}.error.json"
        if error_path.exists():
            error_path.unlink()
        return {"sample_id": sample_id, "status": "ok", "path": str(output_path)}
    except Exception as exc:
        logger.exception("[%s] ACLF assessment failed", sample_id)
        error = {
            "sample_id": sample_id,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_json(args.output_dir / f"{sample_id}.error.json", error)
        return error
    finally:
        rag.close()


async def run_batch(
    patient_ids: list[int],
    *,
    client: AsyncOpenAI,
    config: ACLFConfig,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(config.concurrency)
    agent = ACLFAgent(client=client, model=args.model, config=config)

    async def bounded(pid: int) -> dict[str, Any]:
        async with semaphore:
            return await process_patient(pid, agent=agent, args=args)

    return await asyncio.gather(*(bounded(pid) for pid in patient_ids))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--notes-dir", type=Path, nargs="+", required=True)
    parser.add_argument("--note-dates", type=Path)
    parser.add_argument("--ehr-db", type=Path, required=True)
    parser.add_argument("--vectors-dir", type=Path)
    parser.add_argument("--extraction-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--api-key")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tool-rounds", type=int, default=7)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    patient_ids = load_patient_ids(args.cohort)
    if args.pid is not None:
        patient_ids = [pid for pid in patient_ids if pid == args.pid]
    if args.limit is not None:
        patient_ids = patient_ids[: max(0, args.limit)]
    if not patient_ids:
        raise SystemExit("No matching patients")

    logger.info("Cohort: %d persistent OMOP v1 IDs", len(patient_ids))
    if args.dry_run:
        logger.info("Dry run complete; first IDs: %s", patient_ids[:5])
        return
    for path in (args.cohort, args.mapping, args.ehr_db, *args.notes_dir):
        if not Path(path).exists():
            raise FileNotFoundError(path)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = ACLFConfig(
        concurrency=args.concurrency,
        max_tool_rounds=args.max_tool_rounds,
    )
    client = AsyncOpenAI(
        base_url=normalize_api_base(args.api_base),
        api_key=load_api_key(args.api_key),
        timeout=1800.0,
        max_retries=0,
    )
    results = asyncio.run(run_batch(patient_ids, client=client, config=config, args=args))
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    logger.info("Batch complete: %s", counts)
    if counts.get("failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
