import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "./LoginPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("로그인 페이지", () => {
  it("CardOps 로고와 팀 계정 로그인 화면을 표시합니다", () => {
    render(<LoginPage />);

    expect(screen.getByText("CardOps")).toBeInTheDocument();
    expect(screen.getByLabelText("팀 계정 아이디")).toBeInTheDocument();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "회원가입" }),
    ).toBeInTheDocument();
  });

  it("필수 입력값이 없으면 각 필드의 오류를 표시합니다", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(
      screen.getByText("팀 계정 아이디를 입력해 주세요."),
    ).toBeInTheDocument();
    expect(screen.getByText("비밀번호를 입력해 주세요.")).toBeInTheDocument();
    expect(screen.getByLabelText("팀 계정 아이디")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("비밀번호 표시 상태를 전환합니다", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    const password = screen.getByLabelText("비밀번호");

    expect(password).toHaveAttribute("type", "password");
    await user.click(
      screen.getByRole("button", { name: "비밀번호 표시하기" }),
    );
    expect(password).toHaveAttribute("type", "text");
    expect(
      screen.getByRole("button", { name: "비밀번호 숨기기" }),
    ).toBeInTheDocument();
  });

  it("유효한 입력이면 로그인 API를 호출하고 성공 메시지를 표시합니다", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        user: {
          id: 1,
          username: "analysis_team",
          display_name: "분석팀",
          role: "operations",
          created_at: "2026-08-01T00:00:00Z",
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(screen.getByLabelText("팀 계정 아이디"), "analysis_team");
    await user.type(screen.getByLabelText("비밀번호"), "temporary-password");
    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "분석팀님, 로그인되었습니다.",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("회원가입 모드에서 회원가입 API를 호출합니다", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        user: {
          id: 2,
          username: "analysis_team",
          display_name: "분석팀",
          role: "operations",
          created_at: "2026-08-01T00:00:00Z",
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole("button", { name: "회원가입" }));
    await user.type(screen.getByLabelText("팀 계정 아이디"), "analysis_team");
    await user.type(screen.getByLabelText("표시 이름"), "분석팀");
    await user.type(screen.getByLabelText("비밀번호"), "temporary-password");
    await user.type(
      screen.getByLabelText("비밀번호 확인"),
      "temporary-password",
    );
    await user.click(screen.getByRole("button", { name: "회원가입" }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/signup",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
    );
  });
});
