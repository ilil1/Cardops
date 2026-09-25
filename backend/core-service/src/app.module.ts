import { Module } from '@nestjs/common';
import { AuthModule } from './modules/auth/auth.module';
import { CampaignsModule } from './modules/campaigns/campaigns.module';
import { DatabaseModule } from './infrastructure/database/database.service';
import { AiClientModule } from './infrastructure/ai/ai-client';
import { PredictionController } from './modules/predictions/controllers/prediction.controller';
import { ReadApisModule } from './modules/read-apis/read-apis.module';
import { PredictionService } from './modules/predictions/services/prediction.service';
import { SystemController } from './system.controller';
import { SystemService } from './system.service';

@Module({
  imports: [DatabaseModule, AiClientModule, AuthModule, ReadApisModule, CampaignsModule],
  providers: [PredictionService, SystemService],
  controllers: [SystemController, PredictionController],
})
export class AppModule {}
