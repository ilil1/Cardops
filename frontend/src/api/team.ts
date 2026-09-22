// 관리자용 활성 팀 계정 조회 API 클라이언트입니다.

import { request } from "./client";
import type { components } from "./schema";

export type TeamMember = components["schemas"]["TeamMemberResponse"];
export type UserRole = components["schemas"]["UserRole"];

export function listTeamMembers(includeInactive = false): Promise<TeamMember[]> {
  return request<TeamMember[]>(
    `/api/v1/auth/users?include_inactive=${String(includeInactive)}`,
  );
}

export function updateTeamMember(
  userId: number,
  payload: { role?: UserRole; is_active?: boolean },
): Promise<TeamMember> {
  return request<TeamMember>(`/api/v1/auth/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
