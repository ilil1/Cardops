# Synchrony 전처리·EDA 작업 공간

[`01_data_load_clean.ipynb`](01_data_load_clean.ipynb)에서 고객·거래 원본을 불러오고 데이터 사전, 날짜·식별자·코드의 유효성, 결측치와 관측 기간을 확인합니다. [`02_eda.ipynb`](02_eda.ipynb)는 **ABC Bank 신용카드의 이용·해지 분석**을 위한 EDA입니다. ABC 보유 고객, 구매·반품, 월별 이용·발급·해지, 상품 범주, 최근 미사용·사용 감소와 해지 전 행동을 탐색합니다. 다른 결제수단은 같은 ABC 고객의 같은 기간 거래를 비교하는 보조 분석에 사용합니다.

## 데이터 출처

원본은 [chawanaryan19의 Synchrony Analytics Hackathon 2026 참가 프로젝트](https://github.com/chawanaryan19/Customer-and-Credit-Card-Analysis---Declining-Share-of-Wallet)에 공개된 `Datasets.zip`입니다.

[데이터 README](../../data/README.md)에 다운로드 링크, 문제 설명서, CSV별 구성과 행 수, 거래 기간, 파일 크기와 SHA-256을 정리했습니다.

## 실행

저장소 루트에서 `cardops_venv`를 활성화한 뒤 실행합니다.

```bash
source cardops_venv/bin/activate
# 패키지를 설치하거나 보완해야 할 때 실행합니다.
python -m pip install -r requirements.txt -r src/experiments/synchrony/requirements.txt
cd notebooks/Synchrony
jupyter lab
```

루트의 `requirements.txt`에는 EDA 차트에 필요한 `matplotlib`, `seaborn`과 Jupyter 실행 패키지가 포함되어 있습니다. VS Code에서는 `Cardops (cardops_venv)` 커널을 선택합니다.

두 노트북은 현재 작업 디렉터리에서 상위 경로를 탐색해 저장소 루트를 찾습니다. 저장소 루트에서 Jupyter를 실행해도 사용할 수 있습니다. `02_eda.ipynb`는 동일한 원본 ZIP과 `read_source`로 데이터를 독립적으로 다시 로드하므로, 01의 커널 변수나 실행 상태에 의존하지 않습니다.

## 데이터 경로

- 원본 ZIP: `data/raw/Synchrony/Datasets.zip`
- 향후 정제본: `data/processed/Synchrony/`
- 기존 실험 산출물: `outputs/synchrony_data/` 등

다른 위치의 원본을 사용하려면 노트북의 `SOURCE_ZIP`을 수정하거나 Jupyter 실행 전에 `SYNCHRONY_SOURCE_ZIP` 환경 변수에 경로를 설정합니다. 원본 ZIP과 정제본은 Git에서 제외합니다.

ZIP 내부에는 다음 파일이 필요합니다.

- `Datasets/Customer Data.csv`
- `Datasets/Transaction Data.csv`
- `Datasets/Payment Code.csv`
- `Datasets/Category Code.csv`

## 전처리에서 사용할 기준

- 제공 기록에 수집 누락이 없으며 거래·해지 정보는 기록된 날짜에 이용 가능하다고 가정합니다.
- 관측 기간 내에 고객의 거래 기록이 없으면 해당 기간 거래를 0으로 집계합니다.
- 구매 거래건수는 행 수와 구분하고 `Sale` 행의 `Number_of_Transactions`를 합산합니다. 거래건수가 결측인 반품은 금액과 기록 행 수로 확인합니다.
- 구매와 반품은 `Transaction_Type`으로 구분합니다. 대상 카드 결제는 결제수단 표의 `Payment_Code`를 확인해 선택합니다.
- 해지일이 비어 있는 고객을 결측치라는 이유로 제거하지 않습니다. 기준일까지 발급되어 있고 해지되지 않은 고객을 예측 대상으로 구성합니다.
- EDA 대상은 관측 기간과 ABC 카드 보유 기간이 겹치는 고객입니다. 고객 테이블에서 대상을 먼저 선택하므로 ABC 구매가 0건인 고객도 포함합니다. 발급일 미기록·관측 전 해지·관측 후 발급은 제외 사유를 표시하고 원본에는 유지합니다.
- 현재 카드 상태는 거래 관측 종료시점으로 판단합니다. 그 이후 발급·해지 기록을 당시 상태에 섞지 않습니다. 월별 구매 고객 비율은 월중 보유 고객, 월별 해지 비율은 월초 기존 보유 고객을 분모로 사용합니다.
- 해지 전 행동은 미래 60일이 모두 관측되는 최근 월말을 기준으로, 당시 미해지이고 과거 180일 전체를 관측할 수 있는 고객의 직전·최근 90일을 비교합니다. 이후 60일 해지를 결과로 붙이며, 해지 후 구매 중단이 과거 특징에 섞이지 않게 합니다. 제외된 신규 고객 수를 표시하고 단일 시점의 기술 통계로 해석합니다.
- 타 결제수단 비교는 동일 ABC 고객·동일 기간에 한정합니다. 모든 수단의 구매 금액이 0이면 ABC 금액 비중은 `NaN`이며, 미사용은 제휴몰 내 구매 기록 부재를 뜻합니다. 나이·한도·APR·멤버십은 과거 시점의 값이 보장되지 않아 해지 전 행동 입력에 사용하지 않습니다.
- 기준일까지의 기록으로 모델 입력을 만들고, 이후 기록으로 30일·60일 해지 여부와 다음 달 거래량 정답을 만듭니다. 정답 관측 기간이 끝나지 않은 표본은 정답을 0으로 채우지 않습니다.

## 작업 순서

1. **[01 원본 로드·기본 정제](01_data_load_clean.ipynb)**: 데이터 사전과 기본 규모를 확인하고 날짜 변환, 식별자·결측치·코드 유효성 검사, 관측 기간과 대상 카드 코드 확인을 수행합니다.
2. **[02 ABC 카드 EDA](02_eda.ipynb)**: ABC 대상군과 카드 특성 → ABC 구매·반품 → 월별 사용·발급·해지 → ABC 상품 범주 → 현재 보유 고객의 최근 이용·미사용 → 같은 기준일의 해지 전 행동 비교 → 동일 ABC 고객의 타 결제수단 사용 순서로 탐색합니다.
3. **EDA 이후 모델 입력 준비**: 추가 정제 규칙을 확정하고 예측 기준일별 고객 상태·월별 특징, 분류·회귀 정답과 군집 입력을 구성합니다. 학습·검증·평가 기간과 학습이 필요한 변환의 적용 범위도 정합니다.

EDA의 고객별·월별 집계와 단일 기준일 이후 60일 해지 비교는 패턴 탐색용입니다. 모델용 자료 저장과 여러 기준일의 특징·정답 생성, 학습·검증·평가 기간 분할은 이후 모델 입력 준비 단계에서 다룹니다.

기존 [Synchrony 실험 코드](../../src/experiments/synchrony/README.md)에 원본 로드와 월별 스냅샷 생성 코드가 있습니다. 두 노트북은 그중 `read_source`를 재사용해 날짜 변환, 고객·거래 ID 중복, 고객 연결을 검사합니다. 예측용 월별 특징과 모델 학습은 이후 작업에서 연결합니다.
