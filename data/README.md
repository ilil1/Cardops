# 데이터 디렉터리

원본 데이터와 분석용 정제 데이터를 분리해 데이터 계보를 보존합니다.

## `raw/BankChurners.csv`

- 역할: 외부에서 내려받은 원본 데이터
- 크기: 10,127행 × 23열
- 중복 행: 0
- 실제 `NaN`: 0
- SHA-256: `c91b525a2a6755a1b0b80dad1d0d008ca97ec4df34552c8f47ffa12b6184b779`
- 원칙: 직접 수정하지 않고 [BankChurners 전처리 노트북](../notebooks/BankChurners/01_data_load_clean.ipynb)을 통해 정제본을 생성합니다.

## `processed/bankchurners_clean.csv`

- 역할: EDA와 모델링에서 공통으로 사용하는 정제 데이터
- 크기: 10,127행 × 20열
- 중복 행: 0
- 실제 `NaN`: 0
- SHA-256: `3e8cb3c41920fcaf72189a3ac877098c9c975170f92a58e3504f752fec00c741`

### 정제 규칙

1. `CLIENTNUM` 제거
2. 다음 두 기존 모델 출력 열 제거
   - `Naive_Bayes_Classifier_..._1`
   - `Naive_Bayes_Classifier_..._2`
3. `Attrition_Flag`를 숫자형 `Target`으로 변환
   - `Existing Customer` → `0`
   - `Attrited Customer` → `1`
4. `Education_Level`, `Marital_Status`, `Income_Category`의 `Unknown`은 별도 범주로 유지

정제본은 원본과 행 수 및 공통 열의 값·순서가 동일하며, 위 열 제거와 타깃 변환만 적용되어 있습니다.

## `raw/Synchrony/Datasets.zip`

### 출처와 다운로드

CardOps에서 사용하는 원본은 GitHub 사용자 **chawanaryan19**가 공개한 프로젝트의 `Datasets.zip`입니다. 작성자는 이 프로젝트를 **Synchrony Analytics Hackathon 2026**의 제휴 신용카드 이용 비중(Share of Wallet) 감소와 고객 세분화를 분석한 작업으로 소개합니다. 원본을 확보한 경로는 해당 참가자의 공개 저장소입니다.

- [공개 저장소와 데이터 설명](https://github.com/chawanaryan19/Customer-and-Credit-Card-Analysis---Declining-Share-of-Wallet)
- [원본 ZIP 다운로드](https://raw.githubusercontent.com/chawanaryan19/Customer-and-Credit-Card-Analysis---Declining-Share-of-Wallet/main/Datasets.zip)
- [저장소에 포함된 대회 문제 설명서](https://github.com/chawanaryan19/Customer-and-Credit-Card-Analysis---Declining-Share-of-Wallet/blob/main/Problem%20Statement.pdf)

다운로드한 ZIP을 저장소 루트 기준 `data/raw/Synchrony/Datasets.zip`에 두면 [Synchrony 전처리 노트북](../notebooks/Synchrony/01_data_load_clean.ipynb)에서 바로 읽습니다. ZIP을 미리 압축 해제할 필요는 없습니다.

### 원본 파일 구성

아래 행 수와 열 이름은 **로컬 원본 ZIP을 직접 확인한 값**입니다. ZIP 안의 CSV는 모두 `Datasets/` 디렉터리에 있습니다.

| 파일 | 행 수 | 주요 내용 |
| --- | ---: | --- |
| `Customer Data.csv` | 45,000 | 고객 ID, 나이·성별·멤버십, 카드 발급일·해지일, 한도·APR |
| `Transaction Data.csv` | 446,425 | 고객·거래 ID, 거래일, 금액·건수, 구매·반품 구분, 결제수단·상품 범주 코드 |
| `Payment Code.csv` | 5 | `Payment_Code`와 `Payment_Method` 대응표 |
| `Category Code.csv` | 10 | `Category_Code`와 `Category` 대응표 |

- 거래 관측 기간: **2024-08-01 ~ 2026-07-31**, 총 24개월
- 대상 카드: `Payment_Code = 3`, 결제수단 표의 `ABC Bank Credit Card`
- 거래 범위: 공개 설명에 기재된 `XYZ Inc.` 제휴몰의 거래
- 거래건수: 한 행에 여러 건이 집계될 수 있으므로 **행 수와 `Number_of_Transactions`의 합계는 구분**합니다.
- 날짜 연결: `Customer_ID`로 고객과 거래를 연결하고, `Transaction_Date`, `Credit_Card_Open_Date`, `Credit_Card_Closed_Date`를 사용합니다.

### CardOps에서 사용하는 목적

고객별 거래 날짜와 카드 발급·해지 날짜를 이용해 기준일의 고객 상태를 구성합니다. 기준일까지의 거래로 이후 30일·60일 해지 여부를 예측하는 분류, 다음 달 거래량을 예측하는 회귀, 고객 행동 군집 분석에 활용하는 구조입니다. 각 기능의 구현 상태는 [메인 README](../README.md)와 [기존 Synchrony 실험](../src/experiments/synchrony/README.md)에 정리되어 있습니다.

### 파일 식별과 보관

- 파일 확인일: **2026-09-26**. 최초 다운로드 날짜를 의미하지 않습니다.
- 원본 ZIP 크기: **7,067,993바이트**, 약 7.07MB
- 원본 ZIP SHA-256: `bf66d162bbbf564e93c45623d5a3f89606acb18e6accf3bef157ef1652f4b5cf`
- 사용 위치: [Synchrony 전처리 작업 공간](../notebooks/Synchrony/README.md)

원본 ZIP과 향후 정제본을 저장할 `processed/Synchrony/`는 현재 `.gitignore`로 제외해 로컬에서 관리합니다. 기존 BankChurners 원본·정제본 경로는 유지합니다.

공개 설명에서 실제·합성 데이터 여부와 명시적인 데이터 재사용·재배포 라이선스는 확인되지 않았습니다. 출처 표기는 위 공개 저장소를 기준으로 합니다.

## BankChurners 데이터 출처

[Kaggle — Credit Card Customers](https://www.kaggle.com/datasets/sakshigoyal7/credit-card-customers)
