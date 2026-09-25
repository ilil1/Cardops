import { Injectable, HttpException } from '@nestjs/common';
import { UnitOfWork } from '../../../infrastructure/database/unit-of-work';
import { FaceAuthRepository } from '../repositories/face-auth.repository';
import { AiClient } from '../../../infrastructure/ai/ai-client';
import { AuthService } from './auth.service';
import {
  apiError,
  asObject,
  displayName,
  imageString,
  normalizedUsername,
  publicUser,
  validationError,
  type AuthContext,
  type AuthUser,
} from '../dto/auth.types';

const FACE_LOGIN_RATE_KEY = '@face-login';
const SIMILARITY_THRESHOLD = 0.45;
const TOP2_MARGIN = 0.05;
const MAX_SIGNUP_FRAMES = 50;


function vector(value: number[] | string): number[] {
  const raw = typeof value === 'string' ? JSON.parse(value) as unknown : value;
  if (!Array.isArray(raw) || raw.length === 0 || !raw.every((item) => typeof item === 'number' && Number.isFinite(item))) {
    throw new Error('Invalid stored face embedding.');
  }
  return raw as number[];
}

function normalized(values: number[]): number[] {
  const magnitude = Math.hypot(...values);
  if (!Number.isFinite(magnitude) || magnitude === 0) throw new Error('Invalid face embedding.');
  return values.map((value) => value / magnitude);
}

function averageEmbeddings(frames: number[][]): number[] {
  if (frames.length === 0) throw new Error('No face embeddings were returned.');
  const dimension = frames[0]!.length;
  if (!dimension || frames.some((frame) => frame.length !== dimension)) throw new Error('Inconsistent face embedding dimensions.');
  const mean = Array.from({ length: dimension }, (_, index) =>
    frames.reduce((sum, frame) => sum + frame[index]!, 0) / frames.length);
  return normalized(mean);
}

function similarity(left: number[], right: number[]): number {
  if (left.length !== right.length) return Number.NEGATIVE_INFINITY;
  return left.reduce((sum, value, index) => sum + value * right[index]!, 0);
}

function faceInferenceError(error: unknown): HttpException {
  if (error instanceof HttpException) {
    const response = error.getResponse();
    const detail = typeof response === 'object' && response !== null && 'detail' in response ?
      String(response.detail) : error.message;
    return apiError(error.getStatus(), detail);
  }
  const candidate = error as { status?: number; statusCode?: number; detail?: string; message?: string } | null;
  const status = candidate?.status ?? candidate?.statusCode;
  if (status === 503 || /unavailable|not ready|model.*missing/i.test(candidate?.message ?? '')) {
    return apiError(503, '얼굴 인증 모델이 준비되지 않았습니다. 관리자에게 문의하세요.');
  }
  return apiError(422, candidate?.detail ?? candidate?.message ?? '얼굴 이미지를 처리할 수 없습니다.');
}

function isDuplicateKey(error: unknown): boolean {
  return typeof error === 'object' && error !== null &&
    ('code' in error && error.code === 'ER_DUP_ENTRY' || 'errno' in error && error.errno === 1062);
}

@Injectable()
export class FaceAuthService {
  constructor(
    private readonly unitOfWork: UnitOfWork, private readonly repository: FaceAuthRepository,
    private readonly auth: AuthService,
    private readonly inference: AiClient,
  ) {}

  async availability(): Promise<{ available: boolean; any_enrolled: boolean }> {
    const row = await this.repository.countEnrollments();
    let available = false;
    try { available = await this.inference.faceAvailable(); }
    catch { available = false; }
    return { available, any_enrolled: Number(row?.total ?? 0) > 0 };
  }

  async detect(rawPayload: unknown): Promise<{ face_count: number }> {
    const payload = asObject(rawPayload);
    const image = imageString(payload.image);
    try { return await this.inference.faceDetect(image); }
    catch (error) { throw faceInferenceError(error); }
  }

  async signup(rawPayload: unknown, request: AuthContext) {
    const payload = asObject(rawPayload);
    const username = normalizedUsername(payload.username);
    const name = displayName(payload.display_name);
    if (!Array.isArray(payload.images) || payload.images.length < 1 || payload.images.length > MAX_SIGNUP_FRAMES) {
      throw validationError('images', 'List should have between 1 and 50 items');
    }
    const images = payload.images.map((item) => {
      if (typeof item !== 'string') throw validationError('images', 'Image should be a valid string');
      return item;
    });

    const existing = await this.auth.findUserByUsername(username);
    if (existing) {
      await this.auth.addAuthEvent('signup_requested', username, request, {
        userId: Number(existing.id), metadata: { accepted: false, reason: 'duplicate_username', method: 'face' },
      });
      throw apiError(409, '이미 사용 중인 아이디입니다.');
    }

    let embedding: number[];
    try { embedding = averageEmbeddings(await this.inference.faceEmbed(images, true)); }
    catch (error) { throw faceInferenceError(error); }

    const enrollments = await this.repository.listEnrollments();
    if (enrollments.some((row) => similarity(embedding, vector(row.embedding)) >= SIMILARITY_THRESHOLD)) {
      await this.auth.addAuthEvent('signup_requested', username, request, {
        metadata: { accepted: false, reason: 'duplicate_face', method: 'face' },
      });
      throw apiError(409, '이미 다른 계정에 등록된 얼굴입니다.');
    }

    try {
      return await this.unitOfWork.transaction(async (tx) => {
        const hash = await this.auth.passwordHashForFaceAccount();
        const inserted = await this.repository.createPendingUser(username, name, hash, tx);
        await this.repository.insertCredential(inserted.insertId, JSON.stringify(embedding), images.length, tx);
        await this.auth.addAuthEvent('signup_requested', username, request, {
          userId: inserted.insertId,
          metadata: { accepted: true, approval_status: 'pending', method: 'face', sample_count: images.length },
        }, tx);
        const user = await this.auth.findUserById(inserted.insertId, tx);
        return { user: publicUser(user!) };
      });
    } catch (error) {
      if (isDuplicateKey(error)) throw apiError(409, '이미 사용 중인 아이디입니다.');
      throw error;
    }
  }

  async login(rawPayload: unknown, request: AuthContext) {
    const payload = asObject(rawPayload);
    const image = imageString(payload.image);
    // The FastAPI rate-limit hook is currently disabled for both login methods.
    let probe: number[];
    try {
      const embeddings = await this.inference.faceEmbed([image], false);
      probe = normalized(embeddings[0]!);
    } catch (error) { throw faceInferenceError(error); }

    const reject = async (reason: string): Promise<never> => {
      await this.auth.addAuthEvent('login_failed', FACE_LOGIN_RATE_KEY, request, {
        metadata: { method: 'face', reason },
      });
      throw apiError(401, '등록된 얼굴과 일치하지 않습니다.');
    };

    const enrolled = await this.repository.listActiveEnrollments();
    if (enrolled.length === 0) return reject('no_enrollment');
    const ranked = enrolled.map((row) => ({ userId: Number(row.user_id), score: similarity(probe, vector(row.embedding)) }))
      .sort((left, right) => right.score - left.score);
    if (ranked[0]!.score < SIMILARITY_THRESHOLD ||
        (ranked.length > 1 && ranked[0]!.score - ranked[1]!.score < TOP2_MARGIN)) {
      return reject('no_match');
    }
    const user = await this.auth.findUserById(ranked[0]!.userId);
    if (!user || !Boolean(user.is_active)) return reject('inactive_user');
    const margin = ranked.length > 1 ? ranked[0]!.score - ranked[1]!.score : null;
    await this.auth.addAuthEvent('login_succeeded', user.username, request, {
      userId: Number(user.id),
      metadata: {
        method: 'face',
        similarity: Number(ranked[0]!.score.toFixed(4)),
        margin: margin === null ? null : Number(margin.toFixed(4)),
      },
    });
    return { user: publicUser(user as AuthUser), session: this.auth.issueFaceSession(Number(user.id)) };
  }
}
