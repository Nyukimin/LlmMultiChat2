import argparse
import asyncio
import json
import os

from ingest_mode import run_ingest_mode


def main() -> None:
    ap = argparse.ArgumentParser(description="KB ingest mode")
    ap.add_argument("topic", help="収集対象トピック（例: 吉沢亮 国宝）")
    ap.add_argument("--domain", default="映画", help="対象ドメイン（映画/音楽/小説/漫画/アニメ/ボードゲーム/演劇）")
    ap.add_argument("--rounds", type=int, default=2, help="巡回数（各キャラごとに）")
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "KB", "media.db"), help="DBパス")
    args = ap.parse_args()

    merged = asyncio.run(run_ingest_mode(args.topic, args.domain, args.rounds, args.db))
    print(json.dumps(merged, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
