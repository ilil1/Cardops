import { describe, expect, it } from 'vitest';
import { RequestMethod } from '@nestjs/common';
import { HTTP_CODE_METADATA, METHOD_METADATA, PATH_METADATA } from '@nestjs/common/constants';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { AuthController } from '../auth/auth.controller';
import { FaceAuthController } from '../auth/face-auth.controller';
import { CampaignsController, CustomerContactController } from '../campaigns/campaigns.controller';
import { BulkTargetingController } from '../campaigns/bulk-targeting.controller';
import { PerformanceController } from '../campaigns/performance.controller';
import { InsightsController } from '../read-apis/insights.controller';
import { AnalyticsController } from '../read-apis/analytics.controller';
import { ModelRunsController } from '../read-apis/model-runs.controller';
import { PredictionController } from '../inference/prediction.controller';
import { SystemController } from '../system.controller';

const controllers = [
  AuthController, FaceAuthController, CampaignsController, CustomerContactController,
  BulkTargetingController, PerformanceController, InsightsController, AnalyticsController,
  ModelRunsController, PredictionController, SystemController,
];

function normalized(path: string): string {
  return `/${path.replace(/^\/+|\/+$/g, '').replace(/\/+/g, '/')}`
    .replace(/:[^/]+|\{[^/]+\}/g, '{}');
}

function nestOperations(): Map<string, number> {
  const operations = new Map<string, number>();
  for (const controller of controllers) {
    const base = Reflect.getMetadata(PATH_METADATA, controller) as string | undefined;
    for (const methodName of Object.getOwnPropertyNames(controller.prototype)) {
      if (methodName === 'constructor') continue;
      const handler = (controller.prototype as unknown as Record<string, Function>)[methodName]!;
      const route = Reflect.getMetadata(PATH_METADATA, handler) as string | undefined;
      const requestMethod = Reflect.getMetadata(METHOD_METADATA, handler) as RequestMethod | undefined;
      if (route === undefined || requestMethod === undefined) continue;
      const verb = RequestMethod[requestMethod].toLowerCase();
      const status = Reflect.getMetadata(HTTP_CODE_METADATA, handler) as number | undefined;
      operations.set(`${verb} ${normalized(`${base ?? ''}/${route}`)}`, status ?? (verb === 'post' ? 201 : 200));
    }
  }
  return operations;
}

describe('FastAPI to NestJS HTTP contract', () => {
  it('registers every documented operation with the same success status', () => {
    const document = JSON.parse(readFileSync(resolve(__dirname, '../../openapi.json'), 'utf8')) as {
      paths: Record<string, Record<string, { responses: Record<string, unknown> }>>;
    };
    const expected = new Map<string, number>();
    for (const [path, methods] of Object.entries(document.paths)) {
      for (const [verb, operation] of Object.entries(methods)) {
        if (!['get', 'post', 'patch', 'put', 'delete'].includes(verb)) continue;
        const status = Object.keys(operation.responses).map(Number).find((code) => code >= 200 && code < 300);
        if (status === undefined) throw new Error(`No success response for ${verb} ${path}`);
        expected.set(`${verb} ${normalized(path)}`, status);
      }
    }
    expect(nestOperations()).toEqual(expected);
    expect(expected.size).toBe(46);
  });
});
