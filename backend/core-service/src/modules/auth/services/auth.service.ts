import { Injectable, OnModuleInit } from '@nestjs/common';
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import * as argon2 from 'argon2';
import { UnitOfWork } from '../../../infrastructure/database/unit-of-work';
import type { SqlSession } from '../../../infrastructure/database/database.service';
import { AuthRepository } from '../repositories/auth.repository';
import {
  DEFAULT_SESSION_SECONDS,
  REMEMBERED_SESSION_SECONDS,
  USER_ROLES,
  apiError,
  asObject,
  displayName,
  normalizedUsername,
  publicUser,
  teamMember,
  validationError,
  type AuthContext,
  type LoginResult,
  type AuthSession,
  type AuthUser,
  type PublicUser,
  type TeamMember,
  type UserRole,
} from '../dto/auth.types';


function isDuplicateKey(error: unknown): boolean {
  return typeof error === 'object' && error !== null &&
    ('code' in error && error.code === 'ER_DUP_ENTRY' || 'errno' in error && error.errno === 1062);
}

function parseBooleanQuery(value: unknown): boolean {
  if (value === undefined) return false;
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    const normalized = value.toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(normalized)) return true;
    if (['false', '0', 'no', 'off'].includes(normalized)) return false;
  }
  throw validationError('include_inactive', 'Input should be a valid boolean');
}

@Injectable()
export class AuthService implements OnModuleInit {
  private dummyHash!: string;

  constructor(private readonly unitOfWork: UnitOfWork, private readonly repository: AuthRepository) {}

  async onModuleInit(): Promise<void> {
    if (process.env.DATABASE_URL && (!process.env.JWT_SECRET || process.env.JWT_SECRET.length < 32)) {
      throw new Error('JWT_SECRET must be configured with at least 32 characters when DATABASE_URL is set.');
    }
    this.dummyHash = await argon2.hash('cardops-invalid-login-placeholder', { type: argon2.argon2id });
  }

  private secret(): string {
    const secret = process.env.JWT_SECRET;
    if (!secret) throw apiError(503, 'Authentication is not configured.');
    return secret;
  }

  private signToken(userId: number, lifetimeSeconds: number): string {
    const now = Math.floor(Date.now() / 1000);
    const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
    const payload = Buffer.from(JSON.stringify({ sub: String(userId), iat: now, exp: now + lifetimeSeconds })).toString('base64url');
    const signature = createHmac('sha256', this.secret()).update(`${header}.${payload}`).digest('base64url');
    return `${header}.${payload}.${signature}`;
  }

  private decodeToken(token: string): number {
    const parts = token.split('.');
    if (parts.length !== 3) throw new Error('invalid JWT');
    const header = parts[0]!;
    const payload = parts[1]!;
    const signature = parts[2]!;
    const decodedHeader = JSON.parse(Buffer.from(header, 'base64url').toString('utf8')) as { alg?: string };
    if (decodedHeader.alg !== 'HS256') throw new Error('invalid JWT algorithm');
    const expected = createHmac('sha256', this.secret()).update(`${header}.${payload}`).digest();
    const received = Buffer.from(signature, 'base64url');
    if (received.length !== expected.length || !timingSafeEqual(received, expected)) throw new Error('invalid JWT signature');
    const claims = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as { sub?: unknown; exp?: unknown; iat?: unknown };
    const now = Math.floor(Date.now() / 1000);
    if (claims.exp !== undefined && (typeof claims.exp !== 'number' || claims.exp <= now)) throw new Error('expired JWT');
    if (claims.iat !== undefined && (typeof claims.iat !== 'number' || claims.iat > now)) throw new Error('invalid JWT issue time');
    const userId = Number(claims.sub);
    if (!Number.isSafeInteger(userId) || userId <= 0) throw new Error('invalid JWT subject');
    return userId;
  }

  async addAuthEvent(
    eventType: string,
    username: string | null,
    request: AuthContext | null,
    options: { userId?: number | null; actorId?: number | null; metadata?: Record<string, unknown> | null } = {},
    session?: SqlSession,
  ): Promise<void> {
    await this.repository.insertEvent(options.userId ?? null, username, eventType, request?.ipAddress ?? null, options.actorId ?? null, options.metadata ? JSON.stringify(options.metadata) : null, session);
  }

  async findUserById(id: number, session?: SqlSession): Promise<AuthUser | null> {
    return this.repository.findUserById(id, session);
  }

  async findUserByUsername(username: string, session?: SqlSession): Promise<AuthUser | null> {
    return this.repository.findUserByUsername(username, session);
  }

  async currentUser(request: AuthContext): Promise<AuthUser> {
    const token = request.token;
    if (!token) throw apiError(401, 'Authentication is required.');
    this.secret();
    let userId: number;
    try { userId = this.decodeToken(token); }
    catch { throw apiError(401, 'Invalid or expired authentication.'); }
    const user = await this.findUserById(userId);
    if (!user || !Boolean(user.is_active)) throw apiError(401, 'The authenticated user is no longer available.');
    return user;
  }

  async requireRoles(request: AuthContext, ...roles: UserRole[]): Promise<AuthUser> {
    const user = await this.currentUser(request);
    if (!roles.includes(user.role)) throw apiError(403, 'You do not have permission for this operation.');
    return user;
  }

  async listTeamMembers(request: AuthContext, includeInactiveRaw: unknown): Promise<TeamMember[]> {
    const user = await this.currentUser(request);
    const includeInactive = parseBooleanQuery(includeInactiveRaw);
    if (includeInactive && user.role !== 'admin') throw apiError(403, 'Only administrators can view inactive users.');
    const users = await this.repository.listUsers(includeInactive);
    return users.map(teamMember);
  }

  async updateTeamMember(request: AuthContext, userId: number, rawPayload: unknown): Promise<TeamMember> {
    const actor = await this.requireRoles(request, 'admin');
    const payload = asObject(rawPayload);
    const role = payload.role === undefined || payload.role === null ? undefined : payload.role;
    const active = payload.is_active === undefined || payload.is_active === null ? undefined : payload.is_active;
    if (role === undefined && active === undefined) throw validationError('body', 'At least one user property must be provided.');
    if (role !== undefined && (typeof role !== 'string' || !USER_ROLES.includes(role as UserRole))) {
      throw validationError('role', 'Input should be a valid user role');
    }
    if (active !== undefined && typeof active !== 'boolean') throw validationError('is_active', 'Input should be a valid boolean');

    return this.unitOfWork.transaction(async (tx) => {
      const activeAdmins = await this.repository.lockActiveAdmins(tx);
      const user = activeAdmins.find((candidate) => Number(candidate.id) === userId) ??
        await this.repository.lockUser(userId, tx);
      if (!user) throw apiError(404, 'The team member was not found.');
      const nextRole = (role as UserRole | undefined) ?? user.role;
      const nextActive = (active as boolean | undefined) ?? Boolean(user.is_active);
      if (user.role === 'admin' && nextRole !== 'admin') throw apiError(400, 'Administrator roles cannot be changed to another role.');
      if (userId === Number(actor.id) && !nextActive) throw apiError(400, 'You cannot deactivate your own account.');
      if (user.role === 'admin' && !nextActive && activeAdmins.length <= 1) {
        throw apiError(400, 'At least one active administrator must remain.');
      }
      const before = { role: user.role, is_active: Boolean(user.is_active) };
      await this.repository.updateUser(nextRole, nextActive, userId, tx);
      await this.addAuthEvent('user_updated', user.username, null, {
        userId,
        actorId: Number(actor.id),
        metadata: { before, after: { role: nextRole, is_active: nextActive } },
      }, tx);
      const updated = await this.findUserById(userId, tx);
      return teamMember(updated!);
    });
  }

  async signup(rawPayload: unknown, request: AuthContext): Promise<{ user: PublicUser }> {
    const payload = asObject(rawPayload);
    const username = normalizedUsername(payload.username);
    const name = displayName(payload.display_name);
    if (typeof payload.password !== 'string' || payload.password.length < 8 || payload.password.length > 128) {
      throw validationError('password', 'String should have between 8 and 128 characters');
    }
    const existing = await this.findUserByUsername(username);
    if (existing) {
      await this.addAuthEvent('signup_requested', username, request, {
        userId: Number(existing.id), metadata: { accepted: false, reason: 'duplicate_username' },
      });
      throw apiError(409, 'The username is already registered.');
    }
    try {
      return await this.unitOfWork.transaction(async (tx) => {
        const passwordHash = await argon2.hash(payload.password as string, { type: argon2.argon2id });
        const result = await this.repository.createPendingUser(username, name, passwordHash, tx);
        await this.addAuthEvent('signup_requested', username, request, {
          userId: result.insertId, metadata: { accepted: true, approval_status: 'pending' },
        }, tx);
        const user = await this.findUserById(result.insertId, tx);
        return { user: publicUser(user!) };
      });
    } catch (error) {
      if (isDuplicateKey(error)) throw apiError(409, 'The username is already registered.');
      throw error;
    }
  }

  async login(rawPayload: unknown, request: AuthContext): Promise<LoginResult> {
    const payload = asObject(rawPayload);
    const username = normalizedUsername(payload.username);
    if (typeof payload.password !== 'string' || payload.password.length < 8 || payload.password.length > 128) {
      throw validationError('password', 'String should have between 8 and 128 characters');
    }
    const remember = payload.remember_me === undefined ? false : payload.remember_me;
    if (typeof remember !== 'boolean') throw validationError('remember_me', 'Input should be a valid boolean');
    // The FastAPI rate limit hook currently returns without enforcement.
    const user = await this.findUserByUsername(username);
    let passwordValid = false;
    try { passwordValid = await argon2.verify(user?.password_hash ?? this.dummyHash, payload.password); }
    catch { passwordValid = false; }
    if (!user || !Boolean(user.is_active) || !passwordValid) {
      await this.addAuthEvent('login_failed', username, request, {
        userId: user ? Number(user.id) : null, metadata: { reason: 'invalid_credentials' },
      });
      throw apiError(401, 'Invalid username or password.');
    }
    const lifetime = remember ? REMEMBERED_SESSION_SECONDS : DEFAULT_SESSION_SECONDS;
    const token = this.signToken(Number(user.id), lifetime);
    if (argon2.needsRehash(user.password_hash)) {
      await this.repository.updatePassword(await argon2.hash(payload.password, { type: argon2.argon2id }), user.id);
    }
    await this.addAuthEvent('login_succeeded', username, request, {
      userId: Number(user.id), metadata: { remember_me: remember },
    });
    return { user: publicUser(user), session: { token, lifetimeSeconds: lifetime } };
  }

  async logout(request: AuthContext): Promise<void> {
    const token = request.token;
    if (token && process.env.JWT_SECRET) {
      try {
        const userId = this.decodeToken(token);
        const user = await this.findUserById(userId);
        if (user) await this.addAuthEvent('logout', user.username, request, { userId });
      } catch { /* Invalid cookies do not prevent logout. */ }
    }
  }

  issueFaceSession(userId: number): AuthSession {
    return { token: this.signToken(userId, DEFAULT_SESSION_SECONDS), lifetimeSeconds: DEFAULT_SESSION_SECONDS };
  }

  async passwordHashForFaceAccount(): Promise<string> {
    return argon2.hash(randomBytes(32).toString('base64url'), { type: argon2.argon2id });
  }
}
