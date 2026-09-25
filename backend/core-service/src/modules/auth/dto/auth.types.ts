import { HttpException, HttpStatus } from '@nestjs/common';

export const AUTH_COOKIE_NAME = 'cardops_access_token';
export const DEFAULT_SESSION_SECONDS = 8 * 60 * 60;
export const REMEMBERED_SESSION_SECONDS = 30 * 24 * 60 * 60;
export const USER_ROLES = ['admin', 'analyst', 'operations', 'marketing'] as const;
export type UserRole = (typeof USER_ROLES)[number];

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  password_hash: string;
  role: UserRole;
  is_active: number | boolean;
  created_at: Date | string;
}

export interface PublicUser {
  id: number;
  username: string;
  display_name: string;
  role: UserRole;
  created_at: string;
}

export interface TeamMember extends PublicUser {
  is_active: boolean;
}

export interface AuthRequest {
  cookies?: Record<string, string>;
  headers?: Record<string, unknown>;
  ip?: string;
  socket?: { remoteAddress?: string };
}

export interface AuthResponseWriter {
  cookie(name: string, value: string, options: Record<string, unknown>): void;
  clearCookie(name: string, options: Record<string, unknown>): void;
}

export interface SqlExecutor {
  query(sql: string, params?: unknown[]): Promise<unknown>;
  one(sql: string, params?: unknown[]): Promise<unknown>;
  execute(sql: string, params?: unknown[]): Promise<{ insertId: number; affectedRows: number }>;
}

export function apiError(status: number, detail: string): HttpException {
  return new HttpException({ detail }, status);
}

export function validationError(field: string, message: string): HttpException {
  return new HttpException(
    { detail: [{ type: 'value_error', loc: ['body', field], msg: message }] },
    HttpStatus.UNPROCESSABLE_ENTITY,
  );
}

export function asObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw validationError('body', 'Input should be a valid object');
  }
  return value as Record<string, unknown>;
}

export function normalizedUsername(value: unknown): string {
  if (typeof value !== 'string') throw validationError('username', 'Input should be a valid string');
  const username = value.trim().toLowerCase();
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,49}$/.test(username)) {
    throw validationError('username', 'String should match the username pattern');
  }
  return username;
}

export function displayName(value: unknown): string {
  if (typeof value !== 'string') throw validationError('display_name', 'Input should be a valid string');
  const name = value.trim();
  if (name.length < 1 || name.length > 100) {
    throw validationError('display_name', 'String should have between 1 and 100 characters');
  }
  return name;
}

export function imageString(value: unknown): string {
  if (typeof value !== 'string' || value.length < 32) {
    throw validationError('image', 'String should have at least 32 characters');
  }
  return value;
}

export function utcIso(value: Date | string): string {
  if (value instanceof Date) return value.toISOString();
  const normalized = value.replace(' ', 'T');
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  return new Date(hasZone ? normalized : `${normalized}Z`).toISOString();
}

export function publicUser(user: AuthUser): PublicUser {
  return {
    id: Number(user.id),
    username: user.username,
    display_name: user.display_name,
    role: user.role,
    created_at: utcIso(user.created_at),
  };
}

export function teamMember(user: AuthUser): TeamMember {
  return { ...publicUser(user), is_active: Boolean(user.is_active) };
}

export function integerParam(value: string, field: string): number {
  if (!/^-?\d+$/.test(value) || !Number.isSafeInteger(Number(value))) {
    throw new HttpException(
      { detail: [{ type: 'int_parsing', loc: ['path', field], msg: 'Input should be a valid integer' }] },
      HttpStatus.UNPROCESSABLE_ENTITY,
    );
  }
  return Number(value);
}

/** HTTP 헤더/응답 대신 서비스에 전달하는 인증 문맥입니다. */
export interface AuthContext { token: string | null; ipAddress: string | null; }
export interface AuthSession { token: string; lifetimeSeconds: number; }
export interface LoginResult { user: PublicUser; session: AuthSession; }
