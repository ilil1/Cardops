import { Controller, Get } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { InferenceService } from './inference/inference.service';

const SERVICE = 'Credit Card Customer ML API';
const VERSION = '0.1.0';

@ApiTags('system')
@Controller()
export class SystemController {
  constructor(private readonly inference: InferenceService) {}

  @Get('live')
  live() {
    return { status: 'ok', service: SERVICE, version: VERSION };
  }

  @Get('ready')
  ready() {
    return { status: 'ok', service: SERVICE, version: VERSION, ...this.inference.health };
  }
}
