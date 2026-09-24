import { Global, Module } from '@nestjs/common';
import { AuthController } from './auth.controller';
import { FaceAuthController } from './face-auth.controller';
import { AuthService } from './auth.service';

@Global()
@Module({
  controllers: [AuthController, FaceAuthController],
  providers: [AuthService],
  exports: [AuthService],
})
export class AuthModule {}
