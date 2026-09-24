import { Body, Controller, Get, HttpCode, Param, Patch, Post, Query, Req, Res } from '@nestjs/common';
import { AuthService } from './auth.service';
import { integerParam, publicUser, type AuthRequest, type AuthResponseWriter } from './auth.types';

@Controller('api/v1/auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Get('users')
  async users(@Req() request: AuthRequest, @Query('include_inactive') includeInactive: unknown) {
    return this.auth.listTeamMembers(request, includeInactive);
  }

  @Patch('users/:user_id')
  async updateUser(@Req() request: AuthRequest, @Param('user_id') rawId: string, @Body() payload: unknown) {
    return this.auth.updateTeamMember(request, integerParam(rawId, 'user_id'), payload);
  }

  @Post('signup')
  async signup(@Req() request: AuthRequest, @Body() payload: unknown) {
    return this.auth.signup(payload, request);
  }

  @Post('login')
  @HttpCode(200)
  async login(@Req() request: AuthRequest, @Res({ passthrough: true }) response: AuthResponseWriter, @Body() payload: unknown) {
    return this.auth.login(payload, request, response);
  }

  @Get('me')
  async me(@Req() request: AuthRequest) {
    return publicUser(await this.auth.currentUser(request));
  }

  @Post('logout')
  @HttpCode(204)
  async logout(@Req() request: AuthRequest, @Res({ passthrough: true }) response: AuthResponseWriter): Promise<void> {
    await this.auth.logout(request, response);
  }
}
