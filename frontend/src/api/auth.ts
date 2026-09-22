// Frontend에서 사용하는 인증 API 클라이언트입니다.

import { request } from "./client";
import type { ApiError } from "./client";

export type AuthUser = {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "analyst" | "operations" | "marketing";
  created_at: string;
};

type AuthResponse = {
  user: AuthUser;
};

export type AuthApiError = ApiError;

export function signup(payload: {
  username: string;
  display_name: string;
  password: string;
}): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function login(payload: {
  username: string;
  password: string;
  remember_me: boolean;
}): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCurrentUser(): Promise<AuthUser> {
  return request<AuthUser>("/api/v1/auth/me");
}

export function logout(): Promise<void> {
  return request<void>("/api/v1/auth/logout", { method: "POST" });
}
