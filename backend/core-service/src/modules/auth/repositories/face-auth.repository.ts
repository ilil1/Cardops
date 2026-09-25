import { Injectable } from '@nestjs/common';
import { DatabaseService, type SqlSession } from '../../../infrastructure/database/database.service';
export interface CredentialRow { user_id: number; embedding: number[] | string; }

@Injectable()
export class FaceAuthRepository {
  constructor(private readonly db: DatabaseService) {}

  countEnrollments(session: SqlSession = this.db) {
    return session.one<{ total: number }>('SELECT COUNT(*) AS total FROM user_face_credentials', []);
  }

  listEnrollments(session: SqlSession = this.db) {
    return session.query<CredentialRow>('SELECT user_id, embedding FROM user_face_credentials', []);
  }

  createPendingUser(username: unknown, displayName: unknown, passwordHash: unknown, session: SqlSession = this.db) {
    return session.execute("INSERT INTO users (username, display_name, password_hash, role, is_active) VALUES (?, ?, ?, 'analyst', 0)", [username, displayName, passwordHash]);
  }

  insertCredential(userId: unknown, embedding: unknown, sampleCount: unknown, session: SqlSession = this.db) {
    return session.execute('INSERT INTO user_face_credentials (user_id, embedding, sample_count) VALUES (?, ?, ?)', [userId, embedding, sampleCount]);
  }

  listActiveEnrollments(session: SqlSession = this.db) {
    return session.query<CredentialRow>('SELECT face.user_id, face.embedding FROM user_face_credentials AS face JOIN users AS user ON user.id = face.user_id WHERE user.is_active = 1', []);
  }
}
