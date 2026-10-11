"""Usage: py tools/replay_diagnostic.py RFC_Diagnostic_....zip (read only)."""
import argparse
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diagnostic_replay import replay_diagnostic_zip


def main():
    parser = argparse.ArgumentParser(description="진단 ZIP의 중앙 판정 오프라인 재현 (OBS/원본 파일 변경 없음)")
    parser.add_argument("zip_path")
    args = parser.parse_args()
    with zipfile.ZipFile(args.zip_path) as zf:
        if sum(item.file_size for item in zf.infolist()) > 128 * 1024 * 1024:
            raise ValueError("진단 ZIP의 해제 크기가 안전 한도를 초과합니다.")
        print(json.dumps(replay_diagnostic_zip(zf), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
