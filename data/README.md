# 데이터 디렉터리

원본 데이터와 분석용 정제 데이터를 분리해 데이터 계보를 보존합니다.

## `raw/BankChurners.csv`

- 역할: 외부에서 내려받은 원본 데이터
- 크기: 10,127행 × 23열
- 중복 행: 0
- 실제 `NaN`: 0
- SHA-256: `c91b525a2a6755a1b0b80dad1d0d008ca97ec4df34552c8f47ffa12b6184b779`
- 원칙: 직접 수정하지 않고 `01_data_load_clean.ipynb`를 통해 정제본을 생성합니다.

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

## 데이터 출처

https://www.kaggle.com/datasets/sakshigoyal7/credit-card-customers
