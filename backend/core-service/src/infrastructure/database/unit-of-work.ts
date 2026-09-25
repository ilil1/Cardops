import type { SqlSession } from './database.service';

/** 서비스가 여러 Repository 작업을 하나의 트랜잭션으로 묶는 경계입니다. */
export abstract class UnitOfWork {
  abstract transaction<T>(work: (session: SqlSession) => Promise<T>): Promise<T>;
}
