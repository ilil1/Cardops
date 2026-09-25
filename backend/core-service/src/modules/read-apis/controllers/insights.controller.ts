import { authContext } from '../../auth/controllers/auth-http';
import { Controller, Get, HttpStatus, Param, Query, Req } from '@nestjs/common';
import { AuthService } from '../../auth/services/auth.service';
import { InsightsService } from '../services/insights.service';
import {
  booleanQuery, boundedString, detail, optionalPositiveInteger,
  positiveInteger, riskLevel,
} from '../read-apis.util';

@Controller('api/v1/customer-insights')
export class InsightsController {
  constructor(private readonly service: InsightsService, private readonly auth: AuthService) {}

  @Get()
  async list(@Req() req: any, @Query() query: Record<string, unknown>) {
    await this.auth.currentUser(authContext(req));
    const sortBy = query.sort_by === undefined ? 'churn_probability' : String(query.sort_by);
    const sortOrder = query.sort_order === undefined ? 'desc' : String(query.sort_order);
    const sortFields = [
      'churn_probability', 'actual_transaction_count', 'activity_gap',
      'expected_transaction_count', 'total_trans_amt', 'card_category',
      'contacts_count_12_mon', 'scored_at',
    ];
    if (!sortFields.includes(sortBy)) detail(HttpStatus.UNPROCESSABLE_ENTITY, `Unsupported sort_by: ${sortBy}`);
    if (sortOrder !== 'asc' && sortOrder !== 'desc') detail(HttpStatus.UNPROCESSABLE_ENTITY, `Unsupported sort_order: ${sortOrder}`);
    return this.service.list({
      riskLevel: riskLevel(query.risk_level),
      clusterName: boundedString(query.cluster_name, 'cluster_name'),
      customerId: optionalPositiveInteger(query.customer_id, 'customer_id'),
      campaignCandidatesOnly: booleanQuery(query.campaign_candidates_only),
      campaignId: optionalPositiveInteger(query.campaign_id, 'campaign_id'),
    }, sortBy, sortOrder,
    positiveInteger(query.page, 'page', 1), positiveInteger(query.page_size, 'page_size', 50, 100));
  }

  @Get('coverage/high-risk')
  async coverage(@Req() req: any) {
    await this.auth.currentUser(authContext(req));
    return this.service.highRiskCoverage();
  }

  @Get('reason-codes')
  async reasonCodes(@Req() req: any, @Query('risk_level') risk: unknown) {
    await this.auth.currentUser(authContext(req));
    return this.service.reasonDistribution(riskLevel(risk));
  }

  @Get('dual-signal-count')
  async dualSignal(@Req() req: any) {
    await this.auth.currentUser(authContext(req));
    return this.service.dualSignalCount();
  }

  @Get('history/:customer_id')
  async history(@Req() req: any, @Param('customer_id') id: string, @Query('limit') rawLimit?: string) {
    await this.auth.currentUser(authContext(req));
    return this.service.history(positiveInteger(id, 'customer_id'), positiveInteger(rawLimit, 'limit', 24, 100));
  }

  @Get(':customer_id')
  async customer(@Req() req: any, @Param('customer_id') id: string) {
    await this.auth.currentUser(authContext(req));
    return this.service.detail(positiveInteger(id, 'customer_id'));
  }
}
