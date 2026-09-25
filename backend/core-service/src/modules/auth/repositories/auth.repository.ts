import { Injectable } from '@nestjs/common';
import { DatabaseService, type SqlSession } from '../../../infrastructure/database/database.service';
import type { AuthUser } from '../dto/auth.types';
const USER_COLUMNS = 'id, username, display_name, password_hash, role, is_active, created_at';

@Injectable()
export class AuthRepository {
  constructor(private readonly db: DatabaseService) {}

  insertEvent(userId: unknown, username: unknown, eventType: unknown, ipAddress: unknown, actorId: unknown, metadata: unknown, session: SqlSession = this.db) {
    return session.execute('INSERT INTO auth_events (user_id, username, event_type, ip_address, actor_user_id, metadata_json) VALUES (?, ?, ?, ?, ?, ?)', [userId, username, eventType, ipAddress, actorId, metadata]);
  }

  findUserById(id: unknown, session: SqlSession = this.db) {
    return session.one<AuthUser>(`SELECT ${USER_COLUMNS} FROM users WHERE id = ?`, [id]);
  }

  findUserByUsername(username: unknown, session: SqlSession = this.db) {
    return session.one<AuthUser>(`SELECT ${USER_COLUMNS} FROM users WHERE username = ?`, [username]);
  }

  listUsers(includeInactive: boolean, session: SqlSession = this.db) {
    return session.query<AuthUser>(`SELECT ${USER_COLUMNS} FROM users ${includeInactive ? '' : 'WHERE is_active = 1'} ORDER BY is_active DESC, role ASC, display_name ASC, id ASC`, []);
  }

  lockActiveAdmins(session: SqlSession = this.db) {
    return session.query<AuthUser>(`SELECT ${USER_COLUMNS} FROM users WHERE role = 'admin' AND is_active = 1 ORDER BY id FOR UPDATE`, []);
  }

  lockUser(id: unknown, session: SqlSession = this.db) {
    return session.one<AuthUser>(`SELECT ${USER_COLUMNS} FROM users WHERE id = ? FOR UPDATE`, [id]);
  }

  updateUser(role: unknown, active: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE users SET role = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', [role, active, id]);
  }

  createPendingUser(username: unknown, displayName: unknown, passwordHash: unknown, session: SqlSession = this.db) {
    return session.execute("INSERT INTO users (username, display_name, password_hash, role, is_active) VALUES (?, ?, ?, 'analyst', 0)", [username, displayName, passwordHash]);
  }

  updatePassword(passwordHash: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', [passwordHash, id]);
  }
}
