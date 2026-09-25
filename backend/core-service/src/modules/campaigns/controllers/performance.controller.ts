import { authContext } from '../../auth/controllers/auth-http';
import { Controller, Get, Param, Query, Req } from '@nestjs/common';
import { AuthService } from '../../auth/services/auth.service';
import type { AuthRequest } from '../../auth/dto/auth.types';
import { positiveId, type Row } from '../campaigns.shared';
import { PerformanceService } from '../services/performance.service';

@Controller('api/v1')
export class PerformanceController {
  constructor(private readonly performance: PerformanceService, private readonly auth: AuthService) {}

  @Get('campaign-performance')
  async get(@Req() request: AuthRequest, @Query() query: Row): Promise<Row> {
    await this.auth.currentUser(authContext(request));
    return this.performance.get(query);
  }

  @Get('campaigns/:campaignId/performance')
  async getCampaign(@Req() request: AuthRequest, @Param('campaignId') campaignId: string): Promise<Row> {
    await this.auth.currentUser(authContext(request));
    return this.performance.get({ campaign_id: positiveId(campaignId) });
  }
}
