import { Global, Injectable, Module, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { dirname, join, resolve } from 'node:path';

type WorkerMessage = {
  id?: number;
  ready?: boolean;
  health?: ModelHealth;
  ok?: boolean;
  result?: unknown;
  error?: string | { code: string; message: string };
};

export type ModelHealth = {
  model_loaded: boolean;
  model_name: string;
  model_artifact: string;
  manifest_generated_at: string;
};

export class InferenceError extends Error {
  constructor(message: string, readonly status = 500, readonly code = 'inference_failed') {
    super(message);
  }
}

function projectRoot(): string {
  if (process.env.PYTHON_WORKDIR) return process.env.PYTHON_WORKDIR;
  let directory = resolve(__dirname);
  while (directory !== dirname(directory)) {
    if (existsSync(join(directory, 'backend', 'inference_worker.py'))) return directory;
    directory = dirname(directory);
  }
  throw new Error('Could not locate the Python inference worker.');
}

@Injectable()
export class InferenceService implements OnModuleInit, OnModuleDestroy {
  private child?: ChildProcessWithoutNullStreams;
  private nextId = 1;
  private pending = new Map<number, { resolve: (result: unknown) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }>();
  private modelHealth?: ModelHealth;
  private shuttingDown = false;

  async onModuleInit(): Promise<void> {
    const command = process.env.PYTHON_EXECUTABLE || 'python';
    const child = spawn(command, ['-m', 'backend.inference_worker'], {
      cwd: projectRoot(),
      env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.child = child;
    child.stderr.on('data', (chunk: Buffer) => process.stderr.write(chunk));
    const lines = createInterface({ input: child.stdout });
    await new Promise<void>((resolveReady, rejectReady) => {
      const timeout = setTimeout(() => rejectReady(new Error('Python inference worker startup timed out.')), 120_000);
      let started = false;
      let ready = false;
      lines.on('line', (line) => {
        let message: WorkerMessage;
        try { message = JSON.parse(line) as WorkerMessage; }
        catch { return; }
        if (!started) {
          started = true;
          clearTimeout(timeout);
          if (!message.ready || !message.health) {
            rejectReady(new Error(typeof message.error === 'string' ? message.error : 'Python inference worker failed to start.'));
            return;
          }
          this.modelHealth = message.health;
          ready = true;
          resolveReady();
          return;
        }
        if (message.id === undefined) return;
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        clearTimeout(pending.timer);
        if (message.ok) pending.resolve(message.result);
        else {
          const error = typeof message.error === 'object' ? message.error : { code: 'inference_failed', message: String(message.error) };
          pending.reject(new InferenceError(error.message, error.code === 'unavailable' ? 503 : error.code === 'invalid_face' ? 422 : 500, error.code));
        }
      });
      child.on('error', (error) => { clearTimeout(timeout); rejectReady(error); });
      child.on('exit', (code) => {
        clearTimeout(timeout);
        if (!started) rejectReady(new Error(`Python inference worker exited during startup (${code ?? 'unknown'}).`));
        this.modelHealth = undefined;
        for (const pending of this.pending.values()) {
          clearTimeout(pending.timer);
          pending.reject(new InferenceError('Python inference worker exited.', 503));
        }
        this.pending.clear();
        if (ready && !this.shuttingDown) {
          process.stderr.write(`Python inference worker exited unexpectedly (${code ?? 'unknown'}); restarting API process.\n`);
          process.exit(1);
        }
      });
    });
  }

  get health(): ModelHealth {
    if (!this.modelHealth) throw new InferenceError('The classification model is not ready.', 503);
    return this.modelHealth;
  }

  private call<T>(op: string, payload: Record<string, unknown> = {}): Promise<T> {
    if (!this.child || !this.modelHealth || !this.child.stdin.writable) {
      throw new InferenceError('Python inference worker is unavailable.', 503);
    }
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new InferenceError('Python inference worker timed out.', 503));
      }, 60_000);
      this.pending.set(id, { resolve: resolve as (result: unknown) => void, reject, timer });
      this.child!.stdin.write(JSON.stringify({ id, op, payload }) + '\n', (error) => {
        if (error) {
          clearTimeout(timer);
          this.pending.delete(id);
          reject(new InferenceError(error.message, 503));
        }
      });
    });
  }

  predict(features: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.call('predict', { features });
  }

  faceAvailable(): Promise<boolean> {
    return this.call('face_available');
  }

  faceDetect(image: string): Promise<{ face_count: number }> {
    return this.call('face_detect', { image });
  }

  faceEmbed(images: string[], requireSingle = true): Promise<number[][]> {
    return this.call('face_embed', { images, require_single: requireSingle });
  }

  onModuleDestroy(): void {
    this.shuttingDown = true;
    this.child?.kill();
  }
}

@Global()
@Module({ providers: [InferenceService], exports: [InferenceService] })
export class InferenceModule {}
