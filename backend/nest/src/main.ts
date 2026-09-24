import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { ValidationPipe, UnprocessableEntityException } from '@nestjs/common';
import { SwaggerModule, type OpenAPIObject } from '@nestjs/swagger';
import { json } from 'express';
import cookieParser from 'cookie-parser';
import { config as loadDotEnv } from 'dotenv';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { AppModule } from './app.module';
import { ApiExceptionFilter } from './common/api-exception.filter';

async function bootstrap(): Promise<void> {
  let directory = resolve(process.cwd());
  while (directory !== dirname(directory)) {
    if (existsSync(join(directory, 'backend', 'inference_worker.py'))) {
      loadDotEnv({ path: join(directory, '.env') });
      break;
    }
    directory = dirname(directory);
  }
  const app = await NestFactory.create(AppModule, { bodyParser: false });
  app.use(json({ limit: '60mb' }));
  app.use(cookieParser());
  app.useGlobalFilters(new ApiExceptionFilter());
  app.useGlobalPipes(new ValidationPipe({
    transform: true,
    whitelist: true,
    forbidNonWhitelisted: true,
    exceptionFactory: (errors) => new UnprocessableEntityException({
      detail: errors.map((error) => ({
        loc: ['body', error.property],
        msg: Object.values(error.constraints || {})[0] || 'Invalid value',
        type: 'value_error',
      })),
    }),
  }));
  const origins = (process.env.CORS_ORIGINS || '').split(',').map((value) => value.trim().replace(/\/$/, '')).filter(Boolean);
  if (origins.length) {
    app.enableCors({ origin: origins, credentials: true, methods: ['GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS'] });
  }

  // This checked-in contract preserves the existing schema component names
  // consumed by frontend/src/api/schema.d.ts during the framework migration.
  const document = JSON.parse(readFileSync(resolve(__dirname, '../openapi.json'), 'utf8')) as OpenAPIObject;
  SwaggerModule.setup('docs', app, document, { jsonDocumentUrl: '/openapi.json' });
  app.getHttpAdapter().getInstance().get('/redoc', (_req: unknown, res: { type: (type: string) => { send: (body: string) => void } }) => {
    res.type('html').send('<!doctype html><html><head><title>CardOps API</title></head><body><redoc spec-url="/openapi.json"></redoc><script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script></body></html>');
  });

  await app.listen(Number(process.env.PORT || 8000), '0.0.0.0');
}

void bootstrap();
