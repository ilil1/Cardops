"""분류·회귀·군집 모델을 실행하고 customer_insights에 저장하는 CLI입니다."""

from __future__ import annotations

import argparse
import json
from datetime import date

from backend.app.analysis_batch import DEFAULT_ACTIVITY_GAP_QUANTILE, run_batch
from backend.app.config import get_database_url, get_model_dir
from backend.app.database import initialize_database


def build_parser() -> argparse.ArgumentParser:
    """CLI 인자를 구성합니다."""
    parser = argparse.ArgumentParser(
        description="Score all customers and persist an analysis snapshot."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="같은 데이터·artifact라도 새 분석 스냅샷을 생성합니다.",
    )
    parser.add_argument(
        "--medium-threshold",
        type=float,
        default=0.5,
        help="중위험 이탈 확률 기준(기본값: 0.5)",
    )
    parser.add_argument(
        "--high-threshold",
        type=float,
        default=0.85,
        help="고위험 이탈 확률 기준(기본값: 0.85)",
    )
    parser.add_argument(
        "--activity-gap-quantile",
        type=float,
        default=DEFAULT_ACTIVITY_GAP_QUANTILE,
        help="재활성화 우선 활동성 갭 분위수(기본값: 0.2)",
    )
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        default=None,
        help="분석 기준일(YYYY-MM-DD, 기본값: UTC 오늘)",
    )
    return parser


def main() -> None:
    """환경변수 기반 DB에 배치를 실행합니다."""
    args = build_parser().parse_args()
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to run the analysis batch.")

    engine, session_factory = initialize_database(database_url)
    try:
        with session_factory() as session:
            summary = run_batch(
                session,
                model_dir=get_model_dir(),
                medium_threshold=args.medium_threshold,
                high_threshold=args.high_threshold,
                activity_gap_quantile=args.activity_gap_quantile,
                as_of_date=args.as_of_date,
                force=args.force,
            )
            print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
