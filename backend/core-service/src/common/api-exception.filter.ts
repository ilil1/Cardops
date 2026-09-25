import { ArgumentsHost, Catch, ExceptionFilter, HttpException, HttpStatus, Logger } from '@nestjs/common';
import type { Request, Response } from 'express';

@Catch()
export class ApiExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(ApiExceptionFilter.name);

  catch(error: unknown, host: ArgumentsHost): void {
    const response = host.switchToHttp().getResponse<Response>();
    const request = host.switchToHttp().getRequest<Request>();
    const status = error instanceof HttpException ? error.getStatus() : HttpStatus.INTERNAL_SERVER_ERROR;
    const nestBody = error instanceof HttpException ? error.getResponse() : null;
    const detail = typeof nestBody === 'object' && nestBody !== null && 'detail' in nestBody
      ? (nestBody as { detail: unknown }).detail
      : typeof nestBody === 'string' ? nestBody
      : typeof nestBody === 'object' && nestBody !== null && 'message' in nestBody
        ? (nestBody as { message: unknown }).message
        : status === 404 ? 'Not Found' : 'Internal Server Error';
    if (status >= 500) this.logger.error(`${request.method} ${request.url}: ${error instanceof Error ? error.stack : String(error)}`);
    response.status(status).json({ detail });
  }
}
