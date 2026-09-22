// 로그인 폼에 꽂아 쓰는 얼굴 인증 진입점 — 버튼과 패널을 하나로 묶어
// LoginPage 쪽 수정을 import + 배치 몇 줄로 최소화합니다.
//
// mode="signup"이면 버튼이 속한 <form>에서 accountId·displayName 값을 직접
// 읽어 검증하므로, 호출부는 폼 상태를 넘겨줄 필요가 없습니다.

import { useState, type MouseEvent } from "react";

import type { AuthUser } from "../../api/auth";
import { FaceLoginPanel } from "./FaceLoginPanel";
import "./faceAuth.css";

type FaceAuthLauncherProps = {
  mode: "login" | "signup";
  onLoggedIn?: (user: AuthUser) => void;
  onSignedUp?: () => void;
};

export function FaceAuthLauncher({ mode, onLoggedIn, onSignedUp }: FaceAuthLauncherProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [inlineError, setInlineError] = useState("");
  const [signupInfo, setSignupInfo] = useState<{
    username: string;
    displayName: string;
  } | null>(null);

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    setInlineError("");
    if (mode === "login") {
      setIsOpen(true);
      return;
    }
    // 가입 모드 — 같은 폼의 아이디·표시 이름만 검증합니다(비밀번호 불필요).
    const form = event.currentTarget.form;
    const data = form === null ? null : new FormData(form);
    const username = String(data?.get("accountId") ?? "").trim();
    const displayName = String(data?.get("displayName") ?? "").trim();
    if (username.length < 3) {
      setInlineError("얼굴 가입에는 팀 계정 아이디를 3자 이상 입력해야 합니다.");
      return;
    }
    if (displayName === "") {
      setInlineError("얼굴 가입에는 표시 이름을 입력해야 합니다.");
      return;
    }
    setSignupInfo({ username, displayName });
    setIsOpen(true);
  };

  return (
    <>
      <button className="face-auth-button" type="button" onClick={handleClick}>
        {mode === "login" ? "얼굴로 로그인" : "얼굴 인식으로 회원가입 (비밀번호 없이)"}
      </button>
      {inlineError !== "" && (
        <span className="face-auth-inline-error" role="alert">{inlineError}</span>
      )}
      {isOpen && (
        <FaceLoginPanel
          mode={mode}
          signupInfo={mode === "signup" ? signupInfo ?? undefined : undefined}
          onClose={() => setIsOpen(false)}
          onLoggedIn={(user) => {
            setIsOpen(false);
            onLoggedIn?.(user);
          }}
          onSignedUp={() => {
            setIsOpen(false);
            onSignedUp?.();
          }}
        />
      )}
    </>
  );
}
