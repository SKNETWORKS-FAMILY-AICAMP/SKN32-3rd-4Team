# 로컬 애플리케이션 DB

이 디렉터리는 애플리케이션이 로컬에서 사용하는 데이터베이스 파일을 둔다.

- 기본 SQLite 파일: `insurance.sqlite3`
- 설정: `app/core/config.py`의 `DATABASE_URL`
- 운영·공유 환경에서는 `DATABASE_URL`로 외부 데이터베이스를 지정할 수 있다.
- SQLite 본체와 `-wal`, `-shm` 같은 사이드카 파일은 Git에 커밋하지 않는다.

`app/db/`는 접속 코드와 ORM 모델, `scripts/db/`는 DDL·마이그레이션 스크립트 전용이다.
실제 데이터베이스 파일은 이 디렉터리에서 분리 관리한다.
