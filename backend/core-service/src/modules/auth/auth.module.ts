import { AuthRepository } from './repositories/auth.repository';
import { FaceAuthService } from './services/face-auth.service';
import { FaceAuthRepository } from './repositories/face-auth.repository';
import { Global, Module } from '@nestjs/common';
import { AuthController } from './controllers/auth.controller';
import { FaceAuthController } from './controllers/face-auth.controller';
import { AuthService } from './services/auth.service';

@Global()
@Module({
  controllers: [AuthController, FaceAuthController],
  providers: [AuthRepository, FaceAuthService, FaceAuthRepository, AuthService],
  exports: [AuthService],
})
export class AuthModule {}
