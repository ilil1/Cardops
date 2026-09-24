import { Body, Controller, Get, HttpCode, Param, Patch, Post, Query, Req } from '@nestjs/common';
import { AuthService } from '../auth/auth.service';
import type { AuthRequest } from '../auth/auth.types';
import { CampaignsService } from './campaigns.service';
import { positiveId, type Row } from './campaigns.shared';

@Controller('api/v1')
export class CampaignsController {
  constructor(private readonly campaigns: CampaignsService, private readonly auth: AuthService) {}

  @Get('campaigns')
  async listCampaigns(@Req() request: AuthRequest, @Query() query: Row): Promise<Row> {
    await this.auth.currentUser(request);
    return this.campaigns.listCampaigns(query);
  }

  @Post('campaigns')
  async createCampaign(@Req() request: AuthRequest, @Body() payload: Row): Promise<Row> {
    const actor = await this.auth.requireRoles(request, 'admin', 'marketing');
    return this.campaigns.createCampaign(payload ?? {}, actor);
  }

  @Get('campaigns/:campaignId')
  async getCampaign(@Req() request: AuthRequest, @Param('campaignId') campaignId: string): Promise<Row> {
    await this.auth.currentUser(request);
    return this.campaigns.getCampaign(positiveId(campaignId));
  }

  @Patch('campaigns/:campaignId')
  async updateCampaign(@Req() request: AuthRequest, @Param('campaignId') campaignId: string,
    @Body() payload: Row): Promise<Row> {
    const actor = await this.auth.requireRoles(request, 'admin', 'marketing');
    return this.campaigns.updateCampaign(positiveId(campaignId), payload ?? {}, actor);
  }

  @Get('campaigns/:campaignId/targets')
  async listCampaignTargets(@Req() request: AuthRequest, @Param('campaignId') campaignId: string,
    @Query() query: Row): Promise<Row> {
    await this.auth.currentUser(request);
    return this.campaigns.listTargets({ ...query, campaign_id: positiveId(campaignId) });
  }

  @Get('campaigns/:campaignId/events')
  async listCampaignEvents(@Req() request: AuthRequest, @Param('campaignId') campaignId: string,
    @Query() query: Row): Promise<Row> {
    await this.auth.currentUser(request);
    return this.campaigns.listEvents(positiveId(campaignId), query);
  }

  @Get('campaign-targets/sla-summary')
  async slaSummary(@Req() request: AuthRequest): Promise<Row> {
    await this.auth.currentUser(request);
    return this.campaigns.slaSummary();
  }

  @Get('campaign-targets')
  async listTargets(@Req() request: AuthRequest, @Query() query: Row): Promise<Row> {
    await this.auth.currentUser(request);
    return this.campaigns.listTargets(query);
  }

  @Post('campaign-targets')
  async createTarget(@Req() request: AuthRequest, @Body() payload: Row): Promise<Row> {
    const actor = await this.auth.requireRoles(request, 'admin', 'marketing');
    return this.campaigns.createTarget(payload ?? {}, actor);
  }

  @Patch('campaign-targets/:targetId')
  async updateTarget(@Req() request: AuthRequest, @Param('targetId') targetId: string,
    @Body() payload: Row): Promise<Row> {
    const actor = await this.auth.requireRoles(request, 'admin', 'operations');
    return this.campaigns.updateTarget(positiveId(targetId), payload ?? {}, actor);
  }
}

@Controller('api/v1/customers')
export class CustomerContactController {
  constructor(private readonly campaigns: CampaignsService, private readonly auth: AuthService) {}

  @Patch(':customerId/contact-preferences')
  async updateContactPreferences(@Req() request: AuthRequest, @Param('customerId') customerId: string,
    @Body() payload: Row): Promise<Row> {
    await this.auth.requireRoles(request, 'admin');
    return this.campaigns.updateContactPreferences(positiveId(customerId), payload ?? {});
  }
}
