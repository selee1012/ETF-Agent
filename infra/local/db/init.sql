-- P1-DA-01 로컬 Postgres 최초 기동 시 1회 실행(볼륨이 비어 있을 때만).
-- 마이그레이션(0001·0002)도 IF NOT EXISTS로 같은 확장을 만들기 때문에 이 파일이 없는 Supabase·Azure에서도 동일하게 동작한다.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
