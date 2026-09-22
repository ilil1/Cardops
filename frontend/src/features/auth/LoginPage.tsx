import { useId, useState } from "react";
import type { FormEvent } from "react";

import { login, signup, type AuthUser } from "../../api/auth";
import { FaceAuthLauncher } from "../faceauth/FaceAuthLauncher";

type AuthMode = "login" | "signup";

type FormErrors = {
  accountId?: string;
  displayName?: string;
  password?: string;
  confirmPassword?: string;
};

type LoginPageProps = {
  onAuthenticated?: (user: AuthUser) => void;
};

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <span className="brand-mark__card brand-mark__card--back" />
      <span className="brand-mark__card brand-mark__card--front" />
    </span>
  );
}

function EyeIcon({ hidden }: { hidden: boolean }) {
  if (hidden) {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m3 3 18 18M10.7 10.8a2 2 0 0 0 2.5 2.5M9.9 5.2A10.8 10.8 0 0 1 12 5c5.1 0 8.6 4.2 9.5 6-.4.8-1.3 2.2-2.7 3.5M6.6 6.7C4.5 8 3.1 10 2.5 11.9 3.4 13.7 6.9 18 12 18c1.1 0 2.1-.2 3-.5" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6S2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="2.6" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14M14 7l5 5-5 5" />
    </svg>
  );
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const accountId = useId();
  const displayNameId = useId();
  const passwordId = useId();
  const confirmPasswordId = useId();
  const [mode, setMode] = useState<AuthMode>("login");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [notice, setNotice] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isSignup = mode === "signup";

  const clearFieldError = (field: keyof FormErrors) => {
    setErrors((current) => {
      if (current[field] === undefined) {
        return current;
      }

      return { ...current, [field]: undefined };
    });
    setNotice("");
  };

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setErrors({});
    setNotice("");
    setShowPassword(false);
    setShowConfirmPassword(false);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const accountValue = String(form.get("accountId") ?? "").trim();
    const displayNameValue = String(form.get("displayName") ?? "").trim();
    const passwordValue = String(form.get("password") ?? "");
    const confirmPasswordValue = String(form.get("confirmPassword") ?? "");
    const nextErrors: FormErrors = {};

    if (accountValue === "") {
      nextErrors.accountId = "팀 계정 아이디를 입력해 주세요.";
    }

    if (isSignup && displayNameValue === "") {
      nextErrors.displayName = "표시 이름을 입력해 주세요.";
    }

    if (passwordValue.trim() === "") {
      nextErrors.password = "비밀번호를 입력해 주세요.";
    } else if (isSignup && passwordValue.length < 8) {
      nextErrors.password = "비밀번호는 8자 이상 입력해 주세요.";
    }

    if (isSignup && confirmPasswordValue !== passwordValue) {
      nextErrors.confirmPassword = "비밀번호가 일치하지 않습니다.";
    }

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      setNotice("");
      return;
    }

    setIsSubmitting(true);
    setNotice("");
    try {
      if (isSignup) {
        await signup({
          username: accountValue,
          display_name: displayNameValue,
          password: passwordValue,
        });
        formElement.reset();
        switchMode("login");
        setNotice("가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.");
      } else {
        const result = await login({
          username: accountValue,
          password: passwordValue,
          remember_me: form.get("rememberAccount") === "on",
        });
        onAuthenticated?.(result.user);
        setNotice(`${result.user.display_name}님, 로그인되었습니다.`);
      }
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "요청을 처리하지 못했습니다.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="login-layout">
      <section
        className={`login-panel ${isSignup ? "login-panel--signup" : ""}`}
        aria-label={isSignup ? "팀 계정 회원가입" : "팀 계정 로그인"}
      >
        <div className="login-shell">
          <header className="brand login-brand">
            <BrandMark />
            <span className="brand__copy">
              <strong>CardOps</strong>
              <small>Credit Card Operations Console</small>
            </span>
          </header>

          <div className="login-card">
            <form className="login-form" noValidate onSubmit={handleSubmit}>
              <div className="form-field">
                <label htmlFor={accountId}>팀 계정 아이디</label>
                <input
                  id={accountId}
                  name="accountId"
                  type="text"
                  autoComplete="username"
                  placeholder="예: analysis_team"
                  aria-invalid={errors.accountId !== undefined}
                  aria-describedby={
                    errors.accountId === undefined
                      ? undefined
                      : `${accountId}-error`
                  }
                  onInput={() => clearFieldError("accountId")}
                />
                {errors.accountId !== undefined && (
                  <span className="field-error" id={`${accountId}-error`}>
                    {errors.accountId}
                  </span>
                )}
              </div>

              {isSignup && (
                <div className="form-field">
                  <label htmlFor={displayNameId}>표시 이름</label>
                  <input
                    id={displayNameId}
                    name="displayName"
                    type="text"
                    autoComplete="name"
                    placeholder="예: 분석팀"
                    aria-invalid={errors.displayName !== undefined}
                    aria-describedby={
                      errors.displayName === undefined
                        ? undefined
                        : `${displayNameId}-error`
                    }
                    onInput={() => clearFieldError("displayName")}
                  />
                  {errors.displayName !== undefined && (
                    <span className="field-error" id={`${displayNameId}-error`}>
                      {errors.displayName}
                    </span>
                  )}
                </div>
              )}

              <div className="form-field">
                <label htmlFor={passwordId}>비밀번호</label>
                <div
                  className={`password-input ${
                    errors.password === undefined
                      ? ""
                      : "password-input--error"
                  }`}
                >
                  <input
                    id={passwordId}
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete={isSignup ? "new-password" : "current-password"}
                    placeholder="비밀번호를 입력하세요"
                    aria-invalid={errors.password !== undefined}
                    aria-describedby={
                      errors.password === undefined
                        ? undefined
                        : `${passwordId}-error`
                    }
                    onInput={() => clearFieldError("password")}
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    aria-label={
                      showPassword ? "비밀번호 숨기기" : "비밀번호 표시하기"
                    }
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword((current) => !current)}
                  >
                    <EyeIcon hidden={showPassword} />
                  </button>
                </div>
                {errors.password !== undefined && (
                  <span className="field-error" id={`${passwordId}-error`}>
                    {errors.password}
                  </span>
                )}
              </div>

              {isSignup && (
                <div className="form-field">
                  <label htmlFor={confirmPasswordId}>비밀번호 확인</label>
                  <div
                    className={`password-input ${
                      errors.confirmPassword === undefined
                        ? ""
                        : "password-input--error"
                    }`}
                  >
                    <input
                      id={confirmPasswordId}
                      name="confirmPassword"
                      type={showConfirmPassword ? "text" : "password"}
                      autoComplete="new-password"
                      placeholder="비밀번호를 다시 입력하세요"
                      aria-invalid={errors.confirmPassword !== undefined}
                      aria-describedby={
                        errors.confirmPassword === undefined
                          ? undefined
                          : `${confirmPasswordId}-error`
                      }
                      onInput={() => clearFieldError("confirmPassword")}
                    />
                    <button
                      type="button"
                      className="password-toggle"
                      aria-label={
                        showConfirmPassword
                          ? "비밀번호 확인 숨기기"
                          : "비밀번호 확인 표시하기"
                      }
                      aria-pressed={showConfirmPassword}
                      onClick={() =>
                        setShowConfirmPassword((current) => !current)
                      }
                    >
                      <EyeIcon hidden={showConfirmPassword} />
                    </button>
                  </div>
                  {errors.confirmPassword !== undefined && (
                    <span
                      className="field-error"
                      id={`${confirmPasswordId}-error`}
                    >
                      {errors.confirmPassword}
                    </span>
                  )}
                </div>
              )}

              {!isSignup && (
                <div className="login-form__options">
                  <label className="checkbox">
                    <input type="checkbox" name="rememberAccount" />
                    <span aria-hidden="true" />
                    로그인 상태 유지
                  </label>
                  <span className="account-help">계정 문의 · 관리자</span>
                </div>
              )}

              <button className="submit-button" type="submit" disabled={isSubmitting}>
                {isSubmitting ? "처리 중..." : isSignup ? "회원가입" : "로그인"}
                {!isSubmitting && <ArrowIcon />}
              </button>

              {!isSignup ? (
                <FaceAuthLauncher mode="login" onLoggedIn={(user) => onAuthenticated?.(user)} />
              ) : (
                <FaceAuthLauncher
                  mode="signup"
                  onSignedUp={() => {
                    switchMode("login");
                    setNotice(
                      "얼굴 가입 신청이 접수되었습니다. 관리자 승인 후 '얼굴로 로그인'을 사용할 수 있습니다.",
                    );
                  }}
                />
              )}

              <button
                className="signup-button"
                type="button"
                onClick={() => switchMode(isSignup ? "login" : "signup")}
              >
                {isSignup ? "로그인으로 돌아가기" : "회원가입"}
              </button>

              {notice !== "" && (
                <p className="login-notice" role="status" aria-live="polite">
                  {notice}
                </p>
              )}
            </form>
          </div>

          <footer className="login-panel__footer">
            <span>© 2026 CardOps Console</span>
            <span>v0.1.0</span>
          </footer>
        </div>
      </section>
    </main>
  );
}
