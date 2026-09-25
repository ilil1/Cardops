import { authContext, writeSession } from '../controllers/auth-http';
import { Body, Controller, Get, HttpCode, Post, Req, Res } from '@nestjs/common';
import { FaceAuthService } from '../services/face-auth.service';
import type { AuthRequest, AuthResponseWriter } from '../dto/auth.types';

@Controller('api/v1/auth/face')
export class FaceAuthController {
  constructor(private readonly faces: FaceAuthService) {}

  @Get('availability')
  availability() { return this.faces.availability(); }

  @Post('detect')
  @HttpCode(200)
  detect(@Body() payload: unknown) { return this.faces.detect(payload); }

  @Post('signup')
  signup(@Body() payload: unknown, @Req() request: AuthRequest) {
    return this.faces.signup(payload, authContext(request));
  }

  @Post('login')
  @HttpCode(200)
  async login(@Body() payload: unknown, @Req() request: AuthRequest,
    @Res({ passthrough: true }) response: AuthResponseWriter) {
    const result = await this.faces.login(payload, authContext(request));
    writeSession(response, result.session);
    return { user: result.user };
  }
}
