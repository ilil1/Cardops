import { CampaignsRepository } from './repositories/campaigns.repository';
import { BulkTargetingRepository } from './repositories/bulk-targeting.repository';
import { PerformanceRepository } from './repositories/performance.repository';
import { CampaignEventsRepository } from './repositories/campaign-events.repository';
import { Module } from '@nestjs/common';
import { BulkTargetingController } from './controllers/bulk-targeting.controller';
import { BulkTargetingService } from './services/bulk-targeting.service';
import { CampaignsController, CustomerContactController } from './controllers/campaigns.controller';
import { CampaignsService } from './services/campaigns.service';
import { PerformanceController } from './controllers/performance.controller';
import { PerformanceService } from './services/performance.service';

@Module({
  controllers: [CampaignsController, CustomerContactController, BulkTargetingController, PerformanceController],
  providers: [CampaignsRepository, BulkTargetingRepository, PerformanceRepository, CampaignEventsRepository, CampaignsService, BulkTargetingService, PerformanceService],
})
export class CampaignsModule {}
