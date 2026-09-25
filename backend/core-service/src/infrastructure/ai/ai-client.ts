import { Global, HttpException, Injectable, Module } from '@nestjs/common';

export interface ModelHealth {
  model_loaded: boolean;
  model_name: string;
  model_artifact: string;
  manifest_generated_at: string;
}

/** Python 프로세스 생명주기와 분리된 내부 AI HTTP 클라이언트입니다. */
@Injectable()
export class AiClient {
  private async call<T>(path: string, payload?: unknown): Promise<T> {
    const baseUrl = process.env.AI_SERVICE_URL || 'http://127.0.0.1:8001';
    const token = process.env.AI_SERVICE_TOKEN;
    if (!token) throw new HttpException({ detail: 'AI service authentication is not configured.' }, 503);
    const timeout = Number(process.env.AI_SERVICE_TIMEOUT_MS || 60000);
    if (!Number.isSafeInteger(timeout) || timeout < 1) {
      throw new HttpException({ detail: 'Invalid AI service timeout configuration.' }, 503);
    }
    try {
      const response = await fetch(`${baseUrl.replace(/\/$/, '')}${path}`, {
        method: payload === undefined ? 'GET' : 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Service-Token': token },
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal: AbortSignal.timeout(timeout),
        redirect: 'error',
      });
      const body = await response.json() as T & { detail?: unknown };
      if (!response.ok) {
        const status = response.status === 422 ? 422 : 503;
        throw new HttpException({ detail: status === 422 ? body.detail : 'AI service is unavailable.' }, status);
      }
      return body;
    } catch (error) {
      if (error instanceof HttpException) throw error;
      throw new HttpException({ detail: 'AI service is unavailable or the request timed out.' }, 503);
    }
  }

  async health(): Promise<ModelHealth> {
    const health = await this.call<ModelHealth>('/internal/v1/health');
    if (!health || health.model_loaded !== true || typeof health.model_name !== 'string' ||
        typeof health.model_artifact !== 'string' || typeof health.manifest_generated_at !== 'string') {
      throw new HttpException({ detail: 'AI service returned invalid model health.' }, 503);
    }
    return health;
  }

  predict(features: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.call('/internal/v1/predict', { features });
  }

  async faceAvailable(): Promise<boolean> {
    return (await this.call<{ available: boolean }>('/internal/v1/face/availability')).available;
  }

  faceDetect(image: string): Promise<{ face_count: number }> {
    return this.call('/internal/v1/face/detect', { image });
  }

  async faceEmbed(images: string[], requireSingle = true): Promise<number[][]> {
    return (await this.call<{ embeddings: number[][] }>('/internal/v1/face/embed', {
      images, require_single: requireSingle,
    })).embeddings;
  }
}

@Global()
@Module({ providers: [AiClient], exports: [AiClient] })
export class AiClientModule {}
