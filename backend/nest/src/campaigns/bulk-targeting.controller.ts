import { Body, Controller, Get, HttpCode, Param, Post, Query, Req } from '@nestjs/common';
import { AuthService } from '../auth/auth.service';
import type { AuthRequest } from '../auth/auth.types';
import { BulkTargetingService } from './bulk-targeting.service';
import { positiveId, type Row } from './campaigns.shared';

@Controller('api/v1/campaign-targeting')
export class BulkTargetingController {
  constructor(private readonly service: BulkTargetingService, private readonly auth: AuthService) {}

  @Post('preview')
  async preview(@Req() request: AuthRequest, @Body() payload: Row): Promise<Row> {
    const actor = await this.auth.requireRoles(request, 'admin', 'marketing');
    return this.service.preview(payload ?? {}, actor);
  }

  @Get('runs')
  async list(@Req() request: AuthRequest, @Query() query: Row): Promise<Row> {
    await this.auth.currentUser(request);
    return this.service.list(query);
  }

  @Get('runs/:runId')
  async get(@Req() request: AuthRequest, @Param('runId') runId: string): Promise<Row> {
    await this.auth.currentUser(request);
    return this.service.get(positiveId(runId));
  }

  @Post('runs/:runId/execute')
  @HttpCode(200)
  async execute(@Req() request: AuthRequest, @Param('runId') runId: string): Promise<Row> {
    const actor = await this.auth.requireRoles(request, 'admin', 'marketing');
    return this.service.execute(positiveId(runId), actor);
  }

  @Post('runs/:runId/cancel')
  @HttpCode(200)
  async cancel(@Req() request: AuthRequest, @Param('runId') runId: string): Promise<Row> {
    const actor = await this.auth.requireRoles(request, 'admin', 'marketing');
    return this.service.cancel(positiveId(runId), actor);
  }

  @Post('runs/:runId/rerun')
  async rerun(@Req() request: AuthRequest, @Param('runId') runId: string,
    @Body() payload: Row): Promise<Row> {
    const actor = await this.auth.requireRoles(request, 'admin', 'marketing');
    return this.service.rerun(positiveId(runId), payload ?? {}, actor);
  }
}
