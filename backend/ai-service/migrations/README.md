# Alembic migrations

`versions/`의 파일은 CardOps MySQL 스키마 변경 이력입니다.

- `20260801_0001`: Alembic 도입 전부터 존재하던 `users` 테이블 기준선
- `20260801_0002`: 사용자 역할과 고객 분석·캠페인 테이블 추가

기존 `users` 테이블이 있는 DB는 `migration_runner`가 기준선 revision을 자동으로
stamp한 뒤 최신 migration을 적용합니다. 테이블을 직접 수정하지 마세요.

