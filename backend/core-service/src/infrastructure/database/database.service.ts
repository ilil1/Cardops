import { UnitOfWork } from './unit-of-work';
import { Global, Injectable, Module, OnModuleDestroy, OnModuleInit, ServiceUnavailableException } from '@nestjs/common';
import { readFileSync } from 'node:fs';
import { createPool, type Pool, type PoolConnection, type PoolOptions, type ResultSetHeader, type RowDataPacket } from 'mysql2/promise';

export type SqlParams = readonly unknown[];

export interface SqlSession {
  query<T>(sql: string, params?: SqlParams): Promise<T[]>;
  one<T>(sql: string, params?: SqlParams): Promise<T | null>;
  execute(sql: string, params?: SqlParams): Promise<ResultSetHeader>;
}

function databaseOptions(rawUrl: string): PoolOptions {
  // Existing deployments use SQLAlchemy's URL scheme. Preserve their secrets and
  // connection settings while switching only the driver portion.
  const parsed = new URL(rawUrl.replace(/^mysql\+pymysql:/, 'mysql:'));
  if (parsed.protocol !== 'mysql:') {
    throw new Error('DATABASE_URL must use mysql:// or mysql+pymysql://.');
  }
  const caPath = parsed.searchParams.get('ssl_ca');
  const useTls = caPath !== null || parsed.searchParams.has('ssl_verify_cert') || parsed.searchParams.has('ssl_verify_identity');
  const verifyCertificate = parsed.searchParams.get('ssl_verify_cert') !== 'false';
  const verifyIdentity = parsed.searchParams.get('ssl_verify_identity') !== 'false';
  const tlsOptions = useTls ? {
    ...(caPath ? { ca: readFileSync(caPath, 'utf8') } : {}),
    rejectUnauthorized: verifyCertificate,
    verifyIdentity,
  } as PoolOptions['ssl'] : undefined;
  return {
    host: parsed.hostname,
    port: Number(parsed.port || 3306),
    user: decodeURIComponent(parsed.username),
    password: decodeURIComponent(parsed.password),
    database: decodeURIComponent(parsed.pathname.slice(1)),
    waitForConnections: true,
    connectionLimit: Number(process.env.DB_POOL_SIZE || 10),
    decimalNumbers: true,
    timezone: 'Z',
    ...(tlsOptions ? { ssl: tlsOptions } : {}),
  };
}

async function runQuery<T>(connection: Pool | PoolConnection, sql: string, params: SqlParams = []): Promise<T[]> {
  const [rows] = await connection.query<RowDataPacket[]>(sql, [...params]);
  return rows as T[];
}

async function runExecute(connection: Pool | PoolConnection, sql: string, params: SqlParams = []): Promise<ResultSetHeader> {
  // mysql2 accepts driver values as any[]; callers keep the safer unknown[] API.
  const [result] = await connection.execute<ResultSetHeader>(sql, [...params] as any[]);
  return result;
}

@Injectable()
export class DatabaseService implements SqlSession, OnModuleInit, OnModuleDestroy {
  private readonly pool: Pool | null;

  constructor() {
    this.pool = process.env.DATABASE_URL ? createPool(databaseOptions(process.env.DATABASE_URL)) : null;
  }

  async onModuleInit(): Promise<void> {
    if (!this.pool) return;
    const rows = await this.query<{ table_name: string }>(
      "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'alembic_version'",
    );
    if (rows.length !== 1) {
      throw new Error('Database schema is not migrated. Run the Python Alembic migration before starting NestJS.');
    }
  }

  private connection(): Pool {
    if (!this.pool) throw new ServiceUnavailableException('The database is not configured.');
    return this.pool;
  }

  query<T>(sql: string, params: SqlParams = []): Promise<T[]> {
    return runQuery<T>(this.connection(), sql, params);
  }

  async one<T>(sql: string, params: SqlParams = []): Promise<T | null> {
    return (await this.query<T>(sql, params))[0] ?? null;
  }

  execute(sql: string, params: SqlParams = []): Promise<ResultSetHeader> {
    return runExecute(this.connection(), sql, params);
  }

  async transaction<T>(work: (session: SqlSession) => Promise<T>): Promise<T> {
    const connection = await this.connection().getConnection();
    try {
      await connection.beginTransaction();
      const session: SqlSession = {
        query: <R>(sql: string, params: SqlParams = []) => runQuery<R>(connection, sql, params),
        one: async <R>(sql: string, params: SqlParams = []) => (await runQuery<R>(connection, sql, params))[0] ?? null,
        execute: (sql: string, params: SqlParams = []) => runExecute(connection, sql, params),
      };
      const result = await work(session);
      await connection.commit();
      return result;
    } catch (error) {
      await connection.rollback();
      throw error;
    } finally {
      connection.release();
    }
  }

  async onModuleDestroy(): Promise<void> {
    await this.pool?.end();
  }
}

@Global()
@Module({ providers: [DatabaseService, { provide: UnitOfWork, useExisting: DatabaseService }], exports: [DatabaseService, UnitOfWork] })
export class DatabaseModule {}
