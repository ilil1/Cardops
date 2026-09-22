# 무료 Render 배포

로컬 Docker Compose 설정은 그대로 두고, Render에서는 `render.yaml`을 통해
Frontend Static Site와 Backend Free Web Service를 별도로 만듭니다.

## 1. 무료 데이터베이스 만들기

Render Private Service 대신 TiDB Cloud Starter를 사용합니다. TiDB의 MySQL
호환 접속 정보를 받아 `DATABASE_URL`을 다음 형태로 만듭니다.

```text
mysql+pymysql://<user>:<password>@<host>:4000/<database>
```

TiDB가 요구하는 TLS 옵션이 포함된 연결 문자열을 제공하면 그 값을 그대로
사용합니다.

## 2. Render Blueprint 생성

Git 저장소를 Render에 연결하고 `render.yaml`을 Blueprint로 배포합니다.
처음 생성할 때 다음 비밀 환경변수를 입력합니다.

| 서비스 | 변수 | 값 |
| --- | --- | --- |
| Backend | `DATABASE_URL` | TiDB 연결 문자열 |
| Backend | `CORS_ORIGINS` | `https://cardops-frontend.onrender.com` |
| Frontend | `VITE_API_BASE_URL` | `https://cardops-backend.onrender.com` |

서비스 이름을 바꾸면 두 URL도 실제 Render 주소에 맞춰 바꿉니다. 정적
Frontend의 Vite 환경변수는 빌드 시 번들에 포함되므로 Frontend 환경변수를
수정한 뒤에는 재배포가 필요합니다.

## 3. 모델과 데이터

`outputs/`는 Git에서 제외되어 있으므로 Backend 빌드가 분류 모델을 생성합니다.
현재 설정은 API 기동에 필요한 분류 모델을 생성합니다. 전체 분석 배치에
필요한 회귀·군집 모델은 별도 artifact를 배포하거나 빌드 과정에 추가해야
합니다.

로컬 실행은 계속 기존 `.env`와 `compose.yaml`을 사용합니다.

```powershell
docker compose up -d --build
```
