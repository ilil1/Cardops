import { Body, Controller, HttpCode, Post } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { PredictionService } from '../services/prediction.service';
import { validatePrediction } from '../dto/prediction.dto';

@ApiTags('predictions')
@Controller('api/v1/predictions')
export class PredictionController {
  constructor(private readonly predictions: PredictionService) {}

  @Post()
  @HttpCode(200)
  async predict(@Body() body: unknown): Promise<Record<string, unknown>> {
    const features = validatePrediction(body);
    return this.predictions.predict(features);
  }
}
