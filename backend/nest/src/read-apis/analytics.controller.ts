import { Controller, Get, HttpStatus, Query, Req } from '@nestjs/common';
import { AuthService } from '../auth/auth.service';
import { AnalyticsService, CATEGORICAL_FIELDS, NUMERIC_FIELDS } from './analytics.service';
import { InsightFilters, detail, riskLevel } from './read-apis.util';

@Controller('api/v1/analytics')
export class AnalyticsController {
  constructor(private readonly service: AnalyticsService, private readonly auth: AuthService) {}

  private filters(query: Record<string, unknown>): InsightFilters {
    const customerValue = query.customer_id;
    let customerId: number | undefined;
    if (customerValue !== undefined && customerValue !== null) {
      if (typeof customerValue !== 'string' || !/^-?\d+$/.test(customerValue)) {
        detail(HttpStatus.UNPROCESSABLE_ENTITY, 'customer_id must be an integer.');
      }
      customerId = Number(customerValue);
      if (!Number.isSafeInteger(customerId)) detail(HttpStatus.UNPROCESSABLE_ENTITY, 'customer_id must be an integer.');
    }
    const clusterValue = query.cluster_name;
    if (clusterValue !== undefined && typeof clusterValue !== 'string') {
      detail(HttpStatus.UNPROCESSABLE_ENTITY, 'cluster_name must be a string.');
    }
    return {
      riskLevel: riskLevel(query.risk_level, HttpStatus.BAD_REQUEST),
      clusterName: clusterValue as string | undefined,
      customerId,
    };
  }

  @Get('categorical-churn-rate')
  async categorical(@Req() req: any, @Query() query: Record<string, unknown>) {
    await this.auth.currentUser(req);
    if (query.field === undefined) detail(HttpStatus.UNPROCESSABLE_ENTITY, 'field is required.');
    const field = String(query.field);
    if (!CATEGORICAL_FIELDS.includes(field)) detail(HttpStatus.BAD_REQUEST, `Unsupported categorical field: ${field}`);
    return this.service.categorical(field, this.filters(query));
  }

  @Get('numeric-distribution')
  async numericDistribution(@Req() req: any, @Query() query: Record<string, unknown>) {
    await this.auth.currentUser(req);
    if (query.field === undefined) detail(HttpStatus.UNPROCESSABLE_ENTITY, 'field is required.');
    const field = String(query.field);
    if (!NUMERIC_FIELDS.includes(field)) detail(HttpStatus.BAD_REQUEST, `Unsupported numeric field: ${field}`);
    return this.service.numericDistribution(field, this.filters(query));
  }

  @Get('feature-correlation')
  async correlation(@Req() req: any, @Query() query: Record<string, unknown>) {
    await this.auth.currentUser(req);
    return this.service.featureCorrelation(this.filters(query));
  }

  @Get('cluster-profile')
  async clusterProfile(@Req() req: any, @Query() query: Record<string, unknown>) {
    await this.auth.currentUser(req);
    return this.service.clusterProfile(this.filters(query));
  }

  @Get('risk-cluster-crosstab')
  async riskClusterCrosstab(@Req() req: any, @Query() query: Record<string, unknown>) {
    await this.auth.currentUser(req);
    return this.service.riskClusterCrosstab(this.filters(query));
  }

  @Get('reason-code-cooccurrence')
  async reasonCodeCooccurrence(@Req() req: any, @Query() query: Record<string, unknown>) {
    await this.auth.currentUser(req);
    return this.service.reasonCodeCooccurrence(this.filters(query));
  }
}
