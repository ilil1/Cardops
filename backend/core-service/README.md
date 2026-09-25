# Core Service — NestJS

인증·역할 권한, 고객·분석 조회, 캠페인·대상·일괄 타기팅·성과 API를 담당합니다.

## 레이어드 아키텍처

```text
modules/<기능>/
├── controllers/     # HTTP 요청/응답·쿠키
├── dto/             # 필요한 입력 검증과 전달 타입
├── services/        # 업무 규칙·계산·처리 순서
├── repositories/    # SQL과 저장/조회
└── <기능>.module.ts # Nest 의존성 등록
```

의존 방향은 **Controller → Service → Repository → Database**입니다. AI 추론은 Service → `infrastructure/ai/ai-client.ts` → FastAPI로 전달합니다. 서비스는 원시 SQL을 만들거나 HTTP 응답 객체를 변경하지 않습니다. 여러 저장 작업의 트랜잭션 범위는 `UnitOfWork`로 지정합니다.

## 호스트 실행

저장소 루트 `.env`의 `DATABASE_URL`, `JWT_SECRET`, `AI_SERVICE_TOKEN`, `AI_SERVICE_URL`을 설정합니다. `AI_SERVICE_URL` 기본값은 `http://127.0.0.1:8001`입니다. DB 마이그레이션은 [AI 문서](../ai-service/README.md)의 명령으로 먼저 실행합니다.

```bash
npm --prefix backend/core-service ci
npm --prefix backend/core-service run build
npm --prefix backend/core-service start
```

개발 중에는 `npm --prefix backend/core-service run dev`를 사용합니다. TypeScript watch 빌드가 Nest 생성자 주입에 필요한 decorator metadata를 생성한 뒤 서버를 재시작합니다.

Python 런타임이 Core 프로세스나 이미지에 필요하지 않습니다. AI 서비스가 없어도 Core 자체는 시작되며 예측·얼굴 인증·`/ready` 요청에 503을 반환합니다. Core 포트 기본값은 8000입니다.

## 검증

```bash
npm --prefix backend/core-service run typecheck
npm --prefix backend/core-service test
npm --prefix backend/core-service run build
```

테스트는 공개 API 46개 경로·성공 상태 코드, 레이어 간 의존 방향, 후보 선정·접촉 제한, 조회 통계, 같은 DB 세션의 커밋·롤백, AI HTTP 실패 처리를 확인합니다. 전체 화면과 실제 DB의 모든 조합을 검증하는 테스트는 아닙니다.
