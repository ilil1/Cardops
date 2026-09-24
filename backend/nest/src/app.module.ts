import { Module } from '@nestjs/common';
import { AuthModule } from './auth/auth.module';
import { CampaignsModule } from './campaigns/campaigns.module';
import { DatabaseModule } from './database/database.service';
import { InferenceModule } from './inference/inference.service';
import { PredictionController } from './inference/prediction.controller';
import { ReadApisModule } from './read-apis/read-apis.module';
import { SystemController } from './system.controller';

@Module({
  imports: [DatabaseModule, InferenceModule, AuthModule, ReadApisModule, CampaignsModule],
  controllers: [SystemController, PredictionController],
})
export class AppModule {}
