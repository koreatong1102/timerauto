"""Safely merge chapter fragments from one OBS broadcast.

Creates a new *_recovered.jsonl and TXT without editing or deleting any
original chapter file.  It also salvages older malformed JSONL rows by taking
their title and metadata directly from the row.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


def text_field(line: str, name: str) -> str:
    match = re.search(rf'"{re.escape(name)}"\s*:\s*"(.*?)"(?=,\s*"|\s*\}})', line)
    return match.group(1).strip() if match else ""


def load_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                row = {
                    "wall_time": text_field(line, "wall_time"),
                    "title": text_field(line, "title"),
                    "dedupe_key": text_field(line, "dedupe_key"),
                    "blue_id": text_field(line, "blue_id"),
                    "red_id": text_field(line, "red_id"),
                }
            if isinstance(row, dict) and str(row.get("title") or "").strip():
                rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--stream-start", required=True, help="YYYY-MM-DDTHH:MM:SS")
    parser.add_argument("--output-stem", required=True)
    parser.add_argument("--config", help="TimerAuto config.json; restores registered nicknames")
    parser.add_argument("--offset-sec", type=int, default=0, help="Apply the same chapter timing correction as TimerAuto")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    directory = Path(args.directory)
    stream_start = datetime.fromisoformat(args.stream_start)
    source_paths = [directory / name for name in args.files]
    rows = load_rows(source_paths)
    players: dict[str, str] = {}
    if args.config:
        try:
            players = {
                str(key): str(value)
                for key, value in dict(json.loads(Path(args.config).read_text(encoding="utf-8")).get("players") or {}).items()
            }
        except (OSError, ValueError, TypeError):
            pass

    recovered: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title or title in {"방송 시작", "諛⑹넚 ?쒖옉"}:
            continue
        wall = str(row.get("wall_time") or "").strip()
        try:
            elapsed = max(0, int((datetime.fromisoformat(wall) - stream_start).total_seconds()) + int(args.offset_sec))
        except ValueError:
            elapsed = int(row.get("elapsed_sec") or 0)
        dedupe = str(row.get("dedupe_key") or "").strip()
        blue_id = str(row.get("blue_id") or "").strip()
        red_id = str(row.get("red_id") or "").strip()
        if blue_id and red_id:
            blue_name = players.get(blue_id, blue_id)
            red_name = players.get(red_id, red_id)
            title = f"{blue_name}({blue_id}) VS {red_name}({red_id})"
        key = dedupe or f"{wall}|{title}"
        if key in seen:
            continue
        seen.add(key)
        recovered.append({
            "wall_time": wall,
            "anchor_epoch": stream_start.timestamp(),
            "obs_stream_start_epoch": stream_start.timestamp(),
            "offset_sec": int(args.offset_sec),
            "elapsed_sec": elapsed,
            "title": title,
            "dedupe_key": dedupe,
            "source": "chapter_recovery",
        })
    recovered.sort(key=lambda item: (int(item["elapsed_sec"]), str(item["wall_time"])))

    jsonl_path = directory / f"{args.output_stem}_recovered.jsonl"
    txt_path = directory / f"{args.output_stem}_recovered.txt"
    jsonl_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in recovered), encoding="utf-8")
    lines = [
        "# 챕터 복구본 (원본 파일은 보존됨)",
        f"# 방송 시작: {stream_start.strftime('%Y-%m-%d %H:%M:%S')}",
        f"# 챕터 수: {len(recovered)}",
        "",
    ]
    for row in recovered:
        sec = int(row["elapsed_sec"])
        lines.append(f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d} {row['title']}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(jsonl_path)
    print(txt_path)
    print(f"recovered_events={len(recovered)}")


if __name__ == "__main__":
    main()
