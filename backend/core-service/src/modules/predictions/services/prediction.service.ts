import { Injectable } from '@nestjs/common';
import { AiClient } from '../../../infrastructure/ai/ai-client';

@Injectable()
export class PredictionService {
  constructor(private readonly inference: AiClient) {}

  predict(features: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.inference.predict(features);
  }
}
