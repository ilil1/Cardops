import { Controller, Get, Query, Req } from '@nestjs/common';
import { AuthService } from '../auth/auth.service';
import { ModelRunsService } from './model-runs.service';
import { positiveInteger } from './read-apis.util';

@Controller('api/v1/model-runs')
export class ModelRunsController {
  constructor(private readonly service: ModelRunsService, private readonly auth: AuthService) {}

  @Get('latest')
  async latest(@Req() req: any) {
    await this.auth.currentUser(req);
    return this.service.latest();
  }

  @Get('history')
  async history(@Req() req: any, @Query('limit') limit?: string) {
    await this.auth.currentUser(req);
    return this.service.history(positiveInteger(limit, 'limit', 20, 100));
  }
}
