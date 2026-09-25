import { InsightsRepository } from './repositories/insights.repository';
import { AnalyticsRepository } from './repositories/analytics.repository';
import { ModelRunsRepository } from './repositories/model-runs.repository';
import { Module } from '@nestjs/common';
import { InsightsController } from './controllers/insights.controller';
import { InsightsService } from './services/insights.service';
import { AnalyticsController } from './controllers/analytics.controller';
import { AnalyticsService } from './services/analytics.service';
import { ModelRunsController } from './controllers/model-runs.controller';
import { ModelRunsService } from './services/model-runs.service';

@Module({
  controllers: [InsightsController, AnalyticsController, ModelRunsController],
  providers: [InsightsRepository, AnalyticsRepository, ModelRunsRepository, InsightsService, AnalyticsService, ModelRunsService],
})
export class ReadApisModule {}
