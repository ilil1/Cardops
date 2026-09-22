# CardOps React 프론트엔드

카드 통합 운영 플랫폼의 웹 화면입니다. React를 처음 사용하는 사람도 프로젝트를
실행하고 로그인 화면을 수정할 수 있도록 설치 방법부터 코드 흐름까지 설명합니다.

현재 구현된 화면은 로그인 상태에 따라 반응형 로그인 페이지 또는 인증된 사용자용
대시보드 앱 셸을 표시합니다.

## 1. 현재 구현 상태

구현된 기능:

- 팀 계정 아이디와 비밀번호 입력
- 값을 입력하지 않았을 때 오류 메시지 표시
- 비밀번호 표시·숨김 전환
- 아이디 기억하기 체크박스 UI
- 로그인 버튼
- 회원가입 버튼
- 데스크톱과 모바일 반응형 화면
- 회원가입·로그인 API 호출
- customer_insights 조회 API 클라이언트와 OpenAPI 타입 연결
- HttpOnly 인증 쿠키 기반 로그인 상태 확인
- 로그인 성공 후 인증된 앱 화면으로 전환
- 새로고침 시 `/api/v1/auth/me`를 통한 세션 복원
- 로그아웃 후 로그인 화면 복귀
- 인증 확인 중·오류·재시도 상태 표시
- customer_insights 기반 벤토 그리드 대시보드
- 고객 수·평균 이탈 확률·고위험 고객·군집 요약 카드
- 위험도·군집·고객 ID 필터와 정렬·페이지네이션
- 고객별 분석 결과 목록과 상세 정보 패널
- 예상 거래건수·활동성 갭·군집 신뢰도 표시
- 고객별 분석 이력과 최신 모델 배치·버전 상태 표시
- 고위험 고객 바로가기와 현재 필터 결과 CSV 다운로드
- 캠페인 대상 등록, 담당자 자동 배정, 처리 상태·결과 저장 큐
- analyst 읽기 전용 캠페인 화면과 운영·마케팅·관리자 변경 화면

현재 대시보드 범위에서 제외한 기능:

- 모델 성능 Streamlit 대시보드(`dashboard/app.py`)의 React 화면 통합

모델 성능 화면은 기존 Streamlit 앱으로 별도 실행할 수 있으며, 고객 분석
대시보드는 저장된 분석 결과와 운영 업무 처리에 집중합니다.

로그인과 회원가입은 `/api/v1/auth` 아래의 FastAPI API를 호출합니다. 분석 결과는
`/api/v1/customer-insights` API 클라이언트로 조회할 수 있습니다. Backend는
비밀번호를 Argon2로 해시하고 로그인 성공 시 JavaScript에서 읽을 수 없는
HttpOnly 쿠키를 발급합니다. Frontend는 쿠키를 직접 저장하지 않고
`credentials: "include"`로 요청합니다. 앱 시작 시 `/api/v1/auth/me`를 호출해
쿠키 세션을 확인하며, 인증이 완료된 경우 현재 사용자를 대시보드 앱 셸에 전달합니다.

## 2. 사용 기술

| 기술 | 이 프로젝트에서 하는 일 |
|---|---|
| React 19 | 화면을 컴포넌트 단위로 작성 |
| React DOM | React 컴포넌트를 브라우저의 `#root`에 렌더링 |
| TypeScript 5.9 | JavaScript 코드에 타입 검사를 추가 |
| Vite 8 | 개발 서버 실행과 프로덕션 빌드 |
| pnpm 11 | 프론트엔드 패키지 설치와 명령 실행 |
| ESLint 10 | 실수하기 쉬운 코드와 규칙 위반 검사 |
| Vitest 4 | 단위 테스트 실행 |
| Testing Library | 실제 사용자의 클릭과 입력에 가까운 방식으로 화면 테스트 |
| openapi-typescript | FastAPI OpenAPI 문서를 TypeScript 타입으로 변환 |

`project_venv`는 Python과 FastAPI를 위한 가상환경입니다. React 실행에 필요한
Node.js와 pnpm은 `project_venv`에 포함되지 않으므로 별도로 설치해야 합니다.

## 3. 처음 실행하는 방법

### 3.1 Node.js 확인

이 프로젝트는 Node.js 24 LTS를 사용합니다.

PowerShell에서 다음 명령을 실행합니다.

```powershell
node --version
npm --version
```

정상적인 예:

```text
v24.x.x
11.x.x
```

`node` 명령을 찾을 수 없으면 Node.js 24 LTS를 설치한 뒤 PowerShell을 새로
열어야 합니다.

### 3.2 pnpm 설치

pnpm이 설치되어 있는지 확인합니다.

```powershell
pnpm --version
```

명령을 찾을 수 없으면 다음과 같이 설치합니다.

```powershell
npm install --global pnpm@11.9.0
pnpm --version
```

PowerShell 실행 정책 때문에 `pnpm.ps1`을 실행할 수 없다는 메시지가 나오면
같은 명령을 `pnpm.cmd`로 실행할 수 있습니다.

```powershell
pnpm.cmd --version
```

### 3.3 패키지 설치

프로젝트 루트에서 프론트엔드 디렉터리로 이동합니다.

```powershell
cd frontend
pnpm install --frozen-lockfile
```

이 명령은 `pnpm-lock.yaml`에 기록된 버전대로 패키지를 설치합니다. 설치된
패키지는 `frontend/node_modules/`에 저장되며 Git에는 포함하지 않습니다.

### 3.4 개발 서버 실행

```powershell
pnpm dev
```

정상적으로 실행되면 다음 주소를 브라우저에서 엽니다.

```text
http://127.0.0.1:5173
```

개발 서버가 실행 중인 PowerShell은 종료하지 않습니다. 코드를 저장하면 Vite가
변경 사항을 감지해 브라우저 화면을 자동으로 갱신합니다.

서버를 종료하려면 실행 중인 PowerShell에서 `Ctrl+C`를 누릅니다.

## 4. 파일 구조

```text
frontend/
├── src/
│   ├── app/
│   │   ├── App.test.tsx
│   │   └── App.tsx
│   ├── api/
│   │   ├── auth.ts
│   │   ├── campaigns.ts
│   │   ├── client.ts
│   │   ├── insights.ts
│   │   ├── modelRuns.ts
│   │   ├── team.ts
│   │   └── schema.d.ts
│   ├── features/
│   │   └── auth/
│   │       ├── LoginPage.test.tsx
│   │       └── LoginPage.tsx
│   │   ├── dashboard/
│   │   │   ├── DashboardPage.test.tsx
│   │   │   └── DashboardPage.tsx
│   │   └── department/
│   │       ├── DepartmentDashboardPage.test.tsx
│   │       └── DepartmentDashboardPage.tsx
│   ├── styles/
│   │   └── global.css
│   ├── test/
│   │   ├── environment.test.ts
│   │   └── setup.ts
│   ├── main.tsx
│   └── vite-env.d.ts
├── .gitignore
├── .nvmrc
├── eslint.config.js
├── index.html
├── package.json
├── pnpm-lock.yaml
├── pnpm-workspace.yaml
├── tsconfig.app.json
├── tsconfig.json
├── tsconfig.node.json
└── vite.config.ts
```

### 주요 파일 설명

| 파일 | 역할 | 주로 수정하는 시점 |
|---|---|---|
| `index.html` | 브라우저가 처음 읽는 HTML과 React가 들어갈 `#root` 제공 | 문서 제목이나 meta 태그 변경 |
| `src/main.tsx` | React 앱의 시작점 | 최상위 앱 컴포넌트 연결 |
| `src/app/App.tsx` | 세션 확인과 인증 상태에 따른 화면 전환 | 인증 흐름 변경 |
| `src/features/auth/LoginPage.tsx` | 로그인 화면 구조와 사용자 동작 | 로그인 필드와 버튼, 검증 로직 변경 |
| `src/features/auth/LoginPage.test.tsx` | 로그인 화면 자동 테스트 | 로그인 동작을 변경하거나 기능 추가 |
| `src/features/dashboard/DashboardPage.tsx` | 벤토 그리드 대시보드, 분석 이력·캠페인 큐·상세 패널과 로그아웃 | 대시보드 화면 구현 |
| `src/features/department/DepartmentDashboardPage.tsx` | 운영·마케팅·관리자 전용 업무 화면과 역할별 접근 분기 | 부서별 화면 구현 |
| `src/styles/global.css` | 색상, 크기, 간격과 반응형 디자인 | 로그인 화면 디자인 변경 |
| `src/api/insights.ts` | 고객 분석 목록·상세·이력 API 호출 | 분석 조회 API 변경 |
| `src/api/modelRuns.ts` | 최신 모델 배치 상태 API 호출 | 배치 상태 표시 변경 |
| `src/api/campaigns.ts` | 캠페인 대상 조회·등록·처리 API 호출 | 캠페인 업무 흐름 변경 |
| `src/api/schema.d.ts` | FastAPI에서 생성한 API 요청·응답 타입 | 직접 수정하지 않고 명령으로 재생성 |
| `src/test/setup.ts` | 모든 테스트에 공통 적용되는 준비 코드 | 테스트 라이브러리 설정 변경 |
| `vite.config.ts` | 개발 서버, 프록시와 Vitest 설정 | 포트나 백엔드 주소 변경 |
| `package.json` | 패키지 버전과 실행 명령 정의 | 라이브러리나 script 추가 |
| `pnpm-lock.yaml` | 실제 설치 버전을 고정 | `pnpm install`이 자동 관리 |
| `tsconfig.app.json` | React 코드의 TypeScript 검사 규칙 | 타입 검사 정책 변경 |
| `eslint.config.js` | ESLint 검사 규칙 | 코딩 규칙 변경 |

## 5. 브라우저에 화면이 나타나는 순서

```text
index.html의 <div id="root">
        ↓
src/main.tsx가 #root를 찾음
        ↓
React의 createRoot(...) 실행
        ↓
<App /> 렌더링
        ↓
global.css가 화면 디자인 적용
```

### `main.tsx` 이해하기

```tsx
const rootElement = document.getElementById("root");
```

`index.html`의 `<div id="root"></div>`를 찾습니다. React는 이 요소 안에 화면을
그립니다.

```tsx
createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`<App />`는 먼저 HttpOnly 인증 쿠키로 `/api/v1/auth/me`를 호출합니다. 인증되지
않았으면 `<LoginPage />`를 표시하고, 인증되었으면 `<DashboardPage />`를
표시합니다. HTML처럼 보이는 문법은 JSX라고 부르며, 이 프로젝트에서는
TypeScript와 JSX를 함께 사용하므로 파일 확장자가 `.tsx`입니다.

`StrictMode`는 개발 중 위험한 코드 패턴을 더 쉽게 발견하도록 돕습니다.
개발 환경에서 일부 로직이 두 번 실행되는 것처럼 보일 수 있지만 프로덕션
화면을 두 번 렌더링한다는 의미는 아닙니다.

## 6. React를 처음 배울 때 알아야 할 개념

### 6.1 컴포넌트

컴포넌트는 화면의 한 부분을 반환하는 함수입니다.

```tsx
function BrandMark() {
  return <span className="brand-mark">...</span>;
}
```

`BrandMark`는 CardOps 옆에 표시되는 카드 모양 로고를 담당합니다.
`LoginPage`는 로고, 입력창과 버튼을 조합한 전체 로그인 화면입니다.

React 컴포넌트 이름은 HTML 태그와 구분할 수 있도록 대문자로 시작합니다.

### 6.2 JSX

JSX는 JavaScript 또는 TypeScript 안에서 HTML과 비슷한 구조를 작성하는
문법입니다.

```tsx
<button className="signup-button" type="button">
  회원가입
</button>
```

일반 HTML의 `class` 대신 JSX에서는 `className`을 사용합니다.

### 6.3 상태와 `useState`

상태는 사용자의 동작에 따라 바뀌고 화면에 반영되는 값입니다.

```tsx
const [showPassword, setShowPassword] = useState(false);
```

- `showPassword`: 현재 비밀번호를 보여 줄지 나타내는 값
- `setShowPassword`: `showPassword`를 변경하는 함수
- `false`: 처음에는 비밀번호를 숨긴다는 초기값

버튼을 누르면 다음 코드가 값을 반대로 변경합니다.

```tsx
setShowPassword((current) => !current);
```

상태가 바뀌면 React가 필요한 부분을 다시 렌더링합니다.

### 6.4 이벤트

사용자가 클릭하거나 입력하고 폼을 제출하는 행동을 이벤트라고 합니다.

```tsx
<form onSubmit={handleSubmit}>
```

로그인 버튼이 폼을 제출하면 `handleSubmit` 함수가 실행됩니다.

```tsx
event.preventDefault();
```

브라우저의 기본 폼 제출은 페이지를 새로고침합니다. React가 현재 화면에서
입력값을 검사할 수 있도록 기본 동작을 막습니다.

### 6.5 조건부 렌더링

조건에 따라 화면 요소를 표시하거나 숨길 수 있습니다.

```tsx
{errors.accountId !== undefined && (
  <span className="field-error">{errors.accountId}</span>
)}
```

`errors.accountId`에 오류 메시지가 있을 때만 `<span>`을 렌더링합니다.

### 6.6 `useId`

```tsx
const accountId = useId();
```

`useId`는 입력창에 사용할 고유한 ID를 생성합니다. `<label>`의 `htmlFor`와
`<input>`의 `id`를 연결해 라벨을 눌렀을 때 입력창에 포커스가 이동하고,
스크린 리더도 입력창의 의미를 알 수 있게 합니다.

### 6.7 타입

```tsx
type LoginErrors = {
  accountId?: string;
  password?: string;
};
```

`LoginErrors`는 로그인 오류 객체가 가질 수 있는 값을 정의합니다. `?`는 해당
값이 없을 수도 있다는 뜻입니다. 잘못된 타입을 사용하면 TypeScript가 실행
전에 알려 줍니다.

## 7. 로그인 처리 흐름

로그인 버튼을 눌렀을 때 `handleSubmit`이 실행됩니다.

```text
로그인 버튼 클릭
    ↓
브라우저의 기본 새로고침 방지
    ↓
FormData로 accountId와 password 읽기
    ↓
빈 값인지 검사
    ├─ 빈 값 있음 → 입력창 아래에 오류 표시
    └─ 모두 입력됨 → `/api/v1/auth/login` 호출 → 성공 메시지 표시
```

`noValidate`는 브라우저 기본 오류 팝업을 사용하지 않겠다는 의미입니다. 이
프로젝트는 React 상태를 사용해 동일한 디자인의 오류 메시지를 직접 표시합니다.

입력창에 다시 값을 입력하면 `clearFieldError`가 해당 필드의 기존 오류를
제거합니다.

인증 요청은 `src/api/auth.ts`에 모아 두고, 화면 컴포넌트는 상대 경로로 API를
호출합니다. Vite 개발 프록시가 `/api` 요청을 FastAPI로 전달합니다.

## 8. 스타일 수정 방법

모든 로그인 화면 스타일은 `src/styles/global.css`에 있습니다.

자주 수정하는 선택자:

| 선택자 | 화면 요소 |
|---|---|
| `.login-panel` | 로그인 화면 전체 배경과 바깥 여백 |
| `.login-shell` | 중앙 로그인 영역의 최대 너비 |
| `.login-brand` | CardOps 로고와 글자 |
| `.brand-mark` | 카드 모양 로고 전체 크기 |
| `.brand__copy strong` | CardOps 글자 |
| `.form-field` | 아이디와 비밀번호 입력 영역 |
| `.submit-button` | 로그인 버튼 |
| `.signup-button` | 회원가입 버튼 |
| `.login-panel__footer` | 화면 아래 저작권과 버전 |

예를 들어 로그인 영역을 더 넓히려면 다음 값을 변경합니다.

```css
.login-shell {
  width: min(440px, 100%);
}
```

CardOps 글자를 변경하려면 다음 선택자를 수정합니다.

```css
.brand__copy strong {
  font-size: 30px;
}
```

파일 아래의 `@media (max-width: 480px)`는 화면 너비가 480px 이하일 때 적용되는
모바일 스타일입니다. 공통 스타일을 수정한 뒤 모바일 스타일에서 다시
덮어쓰는 값이 있는지 함께 확인해야 합니다.

## 9. 로그인 화면을 수정할 때의 기준

### 문구나 버튼 추가

`src/features/auth/LoginPage.tsx`의 JSX를 수정합니다.

### 색상, 크기와 간격 변경

`src/styles/global.css`를 수정합니다.

### 클릭했을 때 동작 추가

`LoginPage` 함수 안에 이벤트 함수를 만들고 버튼의 `onClick` 또는 폼의
`onSubmit`에 연결합니다.

### 새 기능을 추가한 뒤

`src/features/auth/LoginPage.test.tsx`에 해당 기능의 테스트도 추가합니다.

## 10. 테스트 이해하기

테스트는 다음 명령으로 한 번 실행합니다.

```powershell
pnpm test
```

코드를 수정하는 동안 계속 감시하려면:

```powershell
pnpm test:watch
```

현재 로그인 테스트는 다음 동작을 확인합니다.

- CardOps, 아이디, 비밀번호와 회원가입 버튼이 표시되는지
- 빈 상태에서 로그인하면 두 입력 오류가 표시되는지
- 비밀번호 표시·숨김이 전환되는지
- 로그인 API 호출과 성공 메시지가 표시되는지
- 회원가입 모드에서 회원가입 API를 호출하는지

Testing Library의 `screen.getByRole`, `screen.getByLabelText`는 CSS 클래스보다
사용자가 인식하는 버튼 이름과 라벨을 기준으로 요소를 찾습니다. 이 방식은
접근성 문제도 함께 발견하는 데 도움이 됩니다.

## 11. 품질 검사 명령

코드를 수정한 뒤 다음 명령을 실행합니다.

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

| 명령 | 검사 내용 |
|---|---|
| `pnpm lint` | ESLint로 코드 규칙과 React Hook 사용 검사 |
| `pnpm typecheck` | TypeScript 타입 오류 검사 |
| `pnpm test` | Vitest 테스트 전체 실행 |
| `pnpm test:watch` | 파일 변경을 감시하며 테스트 반복 실행 |
| `pnpm build` | 타입 검사 후 `dist/`에 배포용 파일 생성 |
| `pnpm preview` | `dist/` 결과를 `127.0.0.1:4173`에서 미리 보기 |

`pnpm build`가 성공해야 실제 배포에 사용할 수 있는 상태라고 볼 수 있습니다.
생성되는 `dist/`는 빌드 결과물이므로 직접 수정하거나 Git에 추가하지 않습니다.

## 12. FastAPI와 연결하는 방법

Vite 개발 서버는 아래 요청을 `http://127.0.0.1:8000`의 FastAPI로 전달합니다.

```text
/api/*
/live
/ready
```

브라우저 코드에서는 FastAPI 주소를 직접 작성하지 않고 상대 경로를 사용합니다.

```ts
const response = await fetch("/api/v1/predictions", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
  },
  body: JSON.stringify(payload),
});
```

개발 환경에서 요청이 이동하는 과정:

```text
React: http://127.0.0.1:5173/api/v1/predictions
                        ↓ Vite proxy
FastAPI: http://127.0.0.1:8000/api/v1/predictions
```

프록시 설정은 `vite.config.ts`에서 확인할 수 있습니다.

인증 API는 다음 경로를 사용합니다.

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/v1/auth/signup` | 팀 계정 회원가입 |
| `POST` | `/api/v1/auth/login` | 로그인 및 HttpOnly 쿠키 발급 |
| `GET` | `/api/v1/auth/me` | 현재 사용자 조회 |
| `GET` | `/api/v1/auth/users` | 활성 담당자 조회, 비활성 포함은 관리자 전용 |
| `PATCH` | `/api/v1/auth/users/{user_id}` | 관리자 전용 역할·활성 상태 변경 |
| `POST` | `/api/v1/auth/logout` | 인증 쿠키 삭제 |

## 13. FastAPI 타입 가져오기

FastAPI가 제공하는 요청·응답 구조를 TypeScript 타입으로 자동 생성할 수
있습니다.

먼저 프로젝트 루트에서 FastAPI를 실행합니다.

```powershell
.\project_venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

다른 PowerShell을 열고 프론트엔드 디렉터리에서 실행합니다.

```powershell
cd frontend
pnpm generate:api
```

생성 결과:

```text
src/api/schema.d.ts
```

이 파일은 자동 생성 파일이므로 직접 수정하지 않습니다. 백엔드 API 구조가
바뀌면 FastAPI를 실행한 상태에서 `pnpm generate:api`를 다시 실행합니다.

## 14. 자주 발생하는 문제

### `127.0.0.1에서 연결을 거부했습니다`

대부분 개발 서버가 실행되지 않았거나 종료된 상태입니다.

```powershell
cd frontend
pnpm dev
```

`Local: http://127.0.0.1:5173/`가 표시되는지 확인합니다.

### `node` 또는 `pnpm` 명령을 찾을 수 없습니다

- Node.js 24 LTS가 설치되어 있는지 확인합니다.
- 설치 후 PowerShell을 완전히 닫고 다시 엽니다.
- `node --version`과 `pnpm --version`을 다시 확인합니다.
- PowerShell 정책 오류라면 `pnpm.cmd`를 사용합니다.

### `Port 5173 is already in use`

이미 프론트엔드 개발 서버가 실행 중일 가능성이 큽니다. 기존 서버가 열린
PowerShell을 확인하고 그 주소를 사용하거나 기존 서버를 `Ctrl+C`로 종료한 뒤
다시 실행합니다.

이 프로젝트는 잘못된 포트로 자동 이동하지 않도록 `strictPort: true`를
사용합니다.

### 로그인 화면은 열리지만 API 요청이 실패합니다

현재 로그인 화면 자체는 FastAPI 없이 열 수 있습니다. 예측 API를 호출할 때는
FastAPI도 별도 PowerShell에서 실행해야 합니다.

```powershell
.\project_venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

다음 주소가 정상인지 확인합니다.

```text
http://127.0.0.1:8000/ready
```

### 패키지 설치 상태가 이상합니다

먼저 lockfile을 기준으로 다시 설치합니다.

```powershell
pnpm install --frozen-lockfile
```

`package.json`의 의존성을 직접 변경했다면 lockfile도 갱신해야 하므로
`pnpm install`을 실행합니다. 의존성을 추가하거나 버전을 바꾼 경우
`package.json`과 `pnpm-lock.yaml`을 함께 관리합니다.

### Vite의 `@emnapi` peer 경고

Vite의 optional WASM fallback 의존성에서 `@emnapi` 관련 peer 경고가 보일 수
있습니다. Windows에서는 네이티브 Rolldown binding을 사용합니다. `lint`,
`typecheck`, `test`, `build`가 모두 성공하면 현재 프로젝트 실행에는 영향을
주지 않습니다.

## 15. 작업할 때 지켜야 할 사항

- `node_modules/`와 `dist/`는 Git에 추가하지 않습니다.
- `src/api/schema.d.ts`는 직접 수정하지 않습니다.
- 화면 동작을 변경하면 관련 테스트도 함께 수정합니다.
- API 주소를 컴포넌트에 직접 반복 작성하지 않습니다.
- 로그인 비밀번호를 로그나 브라우저 저장소에 그대로 남기지 않습니다.
- 인증 토큰은 HttpOnly 쿠키로 관리하고, Backend에서 만료 시간을 설정합니다.
- 코드 변경 후 `lint`, `typecheck`, `test`, `build`를 실행합니다.

## 16. 이후 확장 후보

현재 구현 이후 실제 서비스 요구사항에 따라 확장할 수 있는 항목입니다.

1. 사용자·역할 관리 화면과 역할 변경 API
2. React Router 기반 URL별 부서 페이지
3. 인증 만료 시 공통 재로그인 화면
4. 예측 입력 화면과 `/api/v1/predictions` 연결

Router, 폼 라이브러리, 서버 상태 관리 도구는 실제 요구사항이 정해졌을 때
필요한 것만 추가합니다.
