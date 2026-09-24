import { Module } from '@nestjs/common';
import { InsightsController } from './insights.controller';
import { InsightsService } from './insights.service';
import { AnalyticsController } from './analytics.controller';
import { AnalyticsService } from './analytics.service';
import { ModelRunsController } from './model-runs.controller';
import { ModelRunsService } from './model-runs.service';

@Module({
  controllers: [InsightsController, AnalyticsController, ModelRunsController],
  providers: [InsightsService, AnalyticsService, ModelRunsService],
})
export class ReadApisModule {}
