import { Controller, Get } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { SystemService } from './system.service';

@ApiTags('system')
@Controller()
export class SystemController {
  constructor(private readonly system: SystemService) {}

  @Get('live')
  live() {
    return this.system.live();
  }

  @Get('ready')
  async ready() {
    return this.system.ready();
  }
}
