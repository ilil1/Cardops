// 얼굴 인증 API 클라이언트입니다.
// 웹캠 프레임(JPEG data URL)을 그대로 보내고, 임베딩 추출·매칭은 전부
// 서버가 수행합니다. 클라이언트 임베딩 전송은 재전송 공격에 취약해
// 의도적으로 지원하지 않습니다.

import { request } from "../../api/client";
import type { AuthUser } from "../../api/auth";

type AuthResponse = {
  user: AuthUser;
};

export type FaceAvailability = {
  available: boolean;
  any_enrolled: boolean;
};

export function getFaceAvailability(): Promise<FaceAvailability> {
  return request<FaceAvailability>("/api/v1/auth/face/availability");
}

// 검출만 수행합니다(매칭·레이트리밋 무관). 자동 인증 폴링에 사용합니다.
export function faceDetect(imageDataUrl: string): Promise<{ face_count: number }> {
  return request<{ face_count: number }>("/api/v1/auth/face/detect", {
    method: "POST",
    body: JSON.stringify({ image: imageDataUrl }),
  });
}

export function faceLogin(imageDataUrl: string): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/face/login", {
    method: "POST",
    body: JSON.stringify({ image: imageDataUrl }),
  });
}

// 비밀번호 없이 얼굴만으로 가입합니다. 계정은 관리자 승인 대기 상태로
// 생성되며, 승인 후에는 얼굴 로그인만 사용할 수 있습니다.
export function faceSignup(payload: {
  username: string;
  display_name: string;
  images: string[];
}): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/face/signup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
