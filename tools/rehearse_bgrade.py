"""Offline B-grade commentary audit. Writes only the explicitly chosen output."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commentary_rehearsal import rehearse_archive
from config_model import AppConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output")
    parser.add_argument("--drop-every", type=int, default=0, help="simulate failed speech; never contacts a speech service")
    args = parser.parse_args()
    cfg = AppConfig.from_json(args.config)
    results = [rehearse_archive(path, cfg, drop_every=max(0, args.drop_every)) for path in args.archives]
    if args.output:
        output = Path(args.output).resolve()
        if any(Path(path).resolve() == output.parent or Path(path).resolve() in output.parents for path in args.archives):
            parser.error("output must not be inside a source match archive")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{key: value for key, value in item.items() if key != "transcript"} for item in results], ensure_ascii=False))
    return 1 if any(item["invalid_callbacks"] or item.get("invalid_subjects") or
                    item.get("repeated_optional_topics_75s") for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
