import { afterEach, describe, expect, it, vi } from 'vitest';
import { AiClient } from './ai-client';

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

function setup(response: Response | Error) {
  vi.stubEnv('AI_SERVICE_TOKEN', 'test-service-token');
  vi.stubEnv('AI_SERVICE_URL', 'http://ai-service:8001/');
  const fetch = response instanceof Error ? vi.fn().mockRejectedValue(response) : vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetch);
  return { client: new AiClient(), fetch };
}

describe('AI service HTTP boundary', () => {
  it('sends only inference inputs and a service credential', async () => {
    const { client, fetch } = setup(Response.json({ prediction: 0 }));
    expect(await client.predict({ Customer_Age: 45 })).toEqual({ prediction: 0 });
    expect(fetch).toHaveBeenCalledWith('http://ai-service:8001/internal/v1/predict', expect.objectContaining({
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Service-Token': 'test-service-token' },
      body: JSON.stringify({ features: { Customer_Age: 45 } }), redirect: 'error', signal: expect.any(AbortSignal),
    }));
  });

  it.each([401, 403, 500, 503])('maps upstream %i to a recoverable service failure', async status => {
    const { client } = setup(Response.json({ detail: 'private internal error' }, { status }));
    await expect(client.predict({})).rejects.toMatchObject({ status: 503, response: { detail: 'AI service is unavailable.' } });
  });

  it('preserves invalid-face 422 errors', async () => {
    const { client } = setup(Response.json({ detail: 'No face detected.' }, { status: 422 }));
    await expect(client.faceDetect('bad')).rejects.toMatchObject({ status: 422 });
  });

  it.each([new Error('connection refused'), new DOMException('timed out', 'TimeoutError')])('contains network failure', async error => {
    const { client } = setup(error);
    await expect(client.faceAvailable()).rejects.toMatchObject({ status: 503 });
  });

  it('rejects missing credentials before sending a request', async () => {
    const { client, fetch } = setup(Response.json({}));
    vi.stubEnv('AI_SERVICE_TOKEN', '');
    await expect(client.predict({})).rejects.toMatchObject({ status: 503 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('rejects malformed health responses', async () => {
    const { client } = setup(Response.json({ model_loaded: false }));
    await expect(client.health()).rejects.toMatchObject({ status: 503 });
  });

  it('handles a non-JSON upstream failure', async () => {
    const { client } = setup(new Response('<html>Unavailable</html>', { status: 502 }));
    await expect(client.health()).rejects.toMatchObject({ status: 503 });
  });
});
