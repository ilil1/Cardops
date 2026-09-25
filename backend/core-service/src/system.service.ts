import { Injectable } from '@nestjs/common';
import { AiClient } from './infrastructure/ai/ai-client';

@Injectable()
export class SystemService {
  constructor(private readonly ai: AiClient) {}

  live() {
    return { status: 'ok', service: 'Credit Card Customer ML API', version: '0.1.0' };
  }

  async ready() {
    return { ...this.live(), ...await this.ai.health() };
  }
}
