import { Module } from '@nestjs/common';
import { BulkTargetingController } from './bulk-targeting.controller';
import { BulkTargetingService } from './bulk-targeting.service';
import { CampaignsController, CustomerContactController } from './campaigns.controller';
import { CampaignsService } from './campaigns.service';
import { PerformanceController } from './performance.controller';
import { PerformanceService } from './performance.service';

@Module({
  controllers: [CampaignsController, CustomerContactController, BulkTargetingController, PerformanceController],
  providers: [CampaignsService, BulkTargetingService, PerformanceService],
})
export class CampaignsModule {}
