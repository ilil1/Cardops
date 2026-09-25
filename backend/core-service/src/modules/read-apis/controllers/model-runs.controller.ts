import { authContext } from '../../auth/controllers/auth-http';
import { Controller, Get, Query, Req } from '@nestjs/common';
import { AuthService } from '../../auth/services/auth.service';
import { ModelRunsService } from '../services/model-runs.service';
import { positiveInteger } from '../read-apis.util';

@Controller('api/v1/model-runs')
export class ModelRunsController {
  constructor(private readonly service: ModelRunsService, private readonly auth: AuthService) {}

  @Get('latest')
  async latest(@Req() req: any) {
    await this.auth.currentUser(authContext(req));
    return this.service.latest();
  }

  @Get('history')
  async history(@Req() req: any, @Query('limit') limit?: string) {
    await this.auth.currentUser(authContext(req));
    return this.service.history(positiveInteger(limit, 'limit', 20, 100));
  }
}
