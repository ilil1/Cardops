// 얼굴 자동 인증 패널 — 버튼 없이 얼굴이 확인되면 바로 진행합니다.
//
// 동작 순서:
//   1. 카메라 시작 → 0.7초 간격으로 프레임을 /face/detect에 보내 얼굴 유무만
//      확인합니다(검출 전용이라 로그인 레이트리밋과 무관).
//   2. 얼굴이 확인되는 순간:
//      - login  : 그 프레임으로 /face/login을 1회 호출해 즉시 로그인
//      - signup : 3프레임을 연속 촬영해 /face/signup으로 가입
//   3. 실패(미등록 얼굴·중복 등)하면 자동 재시도하지 않고 멈춥니다 —
//      같은 얼굴을 반복 시도해도 결과가 같고, 실패 로그인은 레이트리밋
//      (15분당 5회)에 집계되기 때문입니다. "다시 시도"로 재개합니다.
//
// 카메라(getUserMedia)는 보안 컨텍스트에서만 동작합니다:
//   - http://localhost, http://127.0.0.1  → 항상 허용 (개발 PC)
//   - https://…                           → 허용 (LAN IP는 mkcert, 배포는 도메인 TLS)
//   - http://<LAN IP>                     → 차단 — 아래에서 원인 안내를 표시합니다.

import { useCallback, useEffect, useRef, useState } from "react";

import type { AuthUser } from "../../api/auth";
import { faceDetect, faceLogin, faceSignup } from "./faceApi";
import "./faceAuth.css";

const DETECT_INTERVAL_MS = 700;
const SIGNUP_FRAME_COUNT = 3;
const SIGNUP_FRAME_INTERVAL_MS = 600;
const CAPTURE_WIDTH = 640;
// 검출 요청이 연속으로 이만큼 실패하면(서버 다운 등) 탐색을 멈춥니다.
const MAX_DETECT_ERRORS = 5;

type Phase = "starting" | "searching" | "processing" | "done" | "failed";

type FaceLoginPanelProps = {
  mode: "login" | "signup";
  onClose: () => void;
  onLoggedIn?: (user: AuthUser) => void;
  // mode="signup"일 때 가입 폼에서 넘겨받는 계정 정보입니다.
  signupInfo?: { username: string; displayName: string };
  onSignedUp?: () => void;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

function cameraUnavailableMessage(error?: unknown): string {
  if (!window.isSecureContext) {
    return (
      "카메라는 HTTPS 또는 localhost에서만 사용할 수 있습니다. " +
      "지금 주소는 보안 연결이 아니라서 브라우저가 카메라를 차단했습니다. " +
      "같은 PC에서는 http://localhost:5173 으로, 다른 기기에서는 https:// 주소로 접속해 주세요."
    );
  }
  // getUserMedia는 호출 자체가 권한 요청입니다. 실패 원인은 DOMException의
  // name으로 구분합니다 — 특히 모바일에서 한 번 "거부"하면 브라우저가 이를
  // 기억해 다시 묻지 않으므로, 사이트 설정에서 풀어야 한다고 안내해야 합니다.
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "PermissionDeniedError") {
      return (
        "카메라 권한이 거부되어 있습니다. 브라우저가 거부를 기억하면 다시 묻지 않으므로, " +
        "주소창의 자물쇠(또는 ⓘ) 아이콘 → 사이트 설정에서 카메라를 '허용'으로 바꾼 뒤 " +
        "페이지를 새로고침해 주세요."
      );
    }
    if (error.name === "NotFoundError" || error.name === "OverconstrainedError") {
      return "사용 가능한 카메라를 찾지 못했습니다. 기기에 카메라가 있는지 확인해 주세요.";
    }
    if (error.name === "NotReadableError") {
      return "다른 앱이 카메라를 사용 중입니다. 카메라를 쓰는 다른 앱·탭을 닫고 다시 시도해 주세요.";
    }
  }
  return "카메라를 사용할 수 없습니다. 브라우저 카메라 권한을 확인해 주세요.";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function FaceLoginPanel({
  mode,
  onClose,
  onLoggedIn,
  signupInfo,
  onSignedUp,
}: FaceLoginPanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [cameraError, setCameraError] = useState("");
  const [isCameraReady, setIsCameraReady] = useState(false);
  const [phase, setPhase] = useState<Phase>("starting");
  const [statusText, setStatusText] = useState("카메라를 준비하는 중입니다...");
  const [notice, setNotice] = useState("");
  // "다시 시도"가 이 값을 올리면 자동 인증 루프가 처음부터 다시 돕니다.
  const [attemptKey, setAttemptKey] = useState(0);

  // ---------------------------------------------------------------- 카메라
  useEffect(() => {
    let cancelled = false;
    const start = async () => {
      if (navigator.mediaDevices === undefined) {
        // 비보안 컨텍스트에서는 mediaDevices 자체가 제공되지 않습니다.
        setCameraError(cameraUnavailableMessage());
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: CAPTURE_WIDTH }, facingMode: "user" },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current !== null) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setIsCameraReady(true);
      } catch (error) {
        setCameraError(cameraUnavailableMessage(error));
      }
    };
    void start();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const captureFrame = useCallback((): string => {
    const video = videoRef.current;
    if (video === null || video.videoWidth === 0) {
      throw new Error("카메라 화면이 아직 준비되지 않았습니다.");
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (context === null) {
      throw new Error("캡처 캔버스를 만들지 못했습니다.");
    }
    context.drawImage(video, 0, 0);
    return canvas.toDataURL("image/jpeg", 0.9);
  }, []);

  // ------------------------------------------------------------ 자동 인증 루프
  useEffect(() => {
    if (!isCameraReady) {
      return;
    }
    let cancelled = false;

    const run = async () => {
      setPhase("searching");
      setNotice("");
      setStatusText("얼굴을 찾는 중입니다. 카메라를 정면으로 바라봐 주세요.");

      // 1단계 — 얼굴이 나타날 때까지 검출 폴링 (레이트리밋 무관)
      let detectErrors = 0;
      let firstFrame = "";
      while (!cancelled) {
        await sleep(DETECT_INTERVAL_MS);
        if (cancelled) {
          return;
        }
        let frame: string;
        try {
          frame = captureFrame();
        } catch {
          continue; // 카메라가 아직 예열 중이면 다음 틱에 재시도
        }
        try {
          const { face_count } = await faceDetect(frame);
          detectErrors = 0;
          if (mode === "signup" && face_count > 1) {
            setStatusText("얼굴이 여러 개 보입니다. 혼자 나온 화면으로 맞춰 주세요.");
            continue;
          }
          if (face_count >= 1) {
            firstFrame = frame;
            break;
          }
          setStatusText("얼굴을 찾는 중입니다. 카메라를 정면으로 바라봐 주세요.");
        } catch (error) {
          detectErrors += 1;
          if (detectErrors >= MAX_DETECT_ERRORS) {
            setPhase("failed");
            setNotice(errorMessage(error));
            return;
          }
        }
      }
      if (cancelled) {
        return;
      }

      // 2단계 — 얼굴 확인됨: 로그인은 1회 시도, 가입은 3프레임 촬영 후 제출
      setPhase("processing");
      try {
        if (mode === "login") {
          setStatusText("얼굴 확인됨 — 로그인하는 중입니다...");
          const result = await faceLogin(firstFrame);
          if (cancelled) {
            return;
          }
          setPhase("done");
          setNotice(`${result.user.display_name}님, 얼굴 인식으로 로그인되었습니다.`);
          onLoggedIn?.(result.user);
        } else {
          if (signupInfo === undefined) {
            throw new Error("가입 정보가 없습니다. 아이디와 표시 이름을 먼저 입력해 주세요.");
          }
          const frames: string[] = [firstFrame];
          setStatusText(`얼굴 확인됨 — 촬영 중 1/${SIGNUP_FRAME_COUNT}`);
          for (let index = 1; index < SIGNUP_FRAME_COUNT; index += 1) {
            await sleep(SIGNUP_FRAME_INTERVAL_MS);
            if (cancelled) {
              return;
            }
            frames.push(captureFrame());
            setStatusText(`얼굴 확인됨 — 촬영 중 ${index + 1}/${SIGNUP_FRAME_COUNT}`);
          }
          setStatusText("가입 처리 중입니다...");
          await faceSignup({
            username: signupInfo.username,
            display_name: signupInfo.displayName,
            images: frames,
          });
          if (cancelled) {
            return;
          }
          setPhase("done");
          setNotice(
            "얼굴 가입 신청이 접수되었습니다. 관리자 승인 후 얼굴 인식만으로 로그인할 수 있습니다.",
          );
          onSignedUp?.();
        }
      } catch (error) {
        if (!cancelled) {
          // 실패 시 자동 재시도하지 않습니다 — 같은 얼굴은 결과가 같고,
          // 실패 로그인은 레이트리밋에 집계됩니다.
          setPhase("failed");
          setNotice(errorMessage(error));
        }
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [isCameraReady, attemptKey, mode, signupInfo, captureFrame, onLoggedIn, onSignedUp]);

  const title = mode === "login" ? "얼굴로 로그인" : "얼굴로 회원가입";

  return (
    <div className="face-panel-overlay" role="dialog" aria-modal="true" aria-label={title}>
      <section className="face-panel">
        <header className="face-panel__heading">
          <h2>{title}</h2>
          <button type="button" className="face-panel__close" aria-label="닫기" onClick={onClose}>
            ×
          </button>
        </header>
        {cameraError !== "" ? (
          <p className="face-panel__error" role="alert">{cameraError}</p>
        ) : (
          <>
            <div className="face-panel__video-wrap">
              {/* 좌우 반전으로 거울처럼 보여줍니다. 서버 전송 프레임은 원본입니다. */}
              <video ref={videoRef} className="face-panel__video" muted playsInline />
            </div>
            {phase !== "done" && phase !== "failed" && (
              <p className="face-panel__status" role="status" aria-live="polite">
                <span className="face-panel__spinner" aria-hidden="true" />
                {statusText}
              </p>
            )}
            {mode === "signup" && phase === "searching" && (
              <p className="face-panel__hint">
                {signupInfo?.username ?? ""} 계정을 얼굴로 만듭니다. 얼굴이 확인되면
                자동으로 {SIGNUP_FRAME_COUNT}장을 촬영해 가입하며, 비밀번호 없이
                얼굴 인식만으로 로그인하게 됩니다.
              </p>
            )}
            {phase === "failed" && (
              <button
                type="button"
                className="face-panel__action"
                onClick={() => setAttemptKey((current) => current + 1)}
              >
                다시 시도
              </button>
            )}
          </>
        )}
        {notice !== "" && (
          <p
            className={phase === "failed" ? "face-panel__error" : "face-panel__notice"}
            role={phase === "failed" ? "alert" : "status"}
            aria-live="polite"
          >
            {notice}
          </p>
        )}
        <p className="face-panel__caveat">
          사진 위·변조 방지(라이브니스)는 지원하지 않는 데모 기능입니다.
          서버에는 얼굴 이미지 대신 수치 임베딩만 저장됩니다.
        </p>
      </section>
    </div>
  );
}
