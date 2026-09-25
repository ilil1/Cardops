# Synchrony 전처리 작업 공간

[`01_data_load_clean.ipynb`](01_data_load_clean.ipynb)에서 고객·거래 원본을 불러오고 날짜, 식별자, 결제수단, 결측치와 관측 기간을 확인합니다. 정제 규칙과 모델별 입력을 이어서 작성할 시작 노트북입니다.

## 데이터 출처

원본은 [chawanaryan19의 Synchrony Analytics Hackathon 2026 참가 프로젝트](https://github.com/chawanaryan19/Customer-and-Credit-Card-Analysis---Declining-Share-of-Wallet)에 공개된 `Datasets.zip`입니다.

[데이터 README](../../data/README.md)에 다운로드 링크, 문제 설명서, CSV별 구성과 행 수, 거래 기간, 파일 크기와 SHA-256을 정리했습니다.

## 실행

저장소 루트에서 Synchrony 분석용 Python 환경을 활성화한 뒤 실행합니다.

```bash
python -m pip install -r src/experiments/synchrony/requirements.txt
python -m pip install 'jupyterlab>=4,<5' 'ipykernel>=6,<9'
cd notebooks/Synchrony
jupyter lab
```

노트북은 현재 작업 디렉터리에서 상위 경로를 탐색해 저장소 루트를 찾습니다. 저장소 루트에서 Jupyter를 실행해도 사용할 수 있습니다.

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
- 거래건수는 행 수와 구분하고 `Number_of_Transactions`를 합산합니다.
- 구매와 반품은 `Transaction_Type`으로 구분합니다. 대상 카드 결제는 결제수단 표의 `Payment_Code`를 확인해 선택합니다.
- 해지일이 비어 있는 고객을 결측치라는 이유로 제거하지 않습니다. 기준일까지 발급되어 있고 해지되지 않은 고객을 예측 대상으로 구성합니다.
- 기준일까지의 기록으로 모델 입력을 만들고, 이후 기록으로 30일·60일 해지 여부와 다음 달 거래량 정답을 만듭니다. 정답 관측 기간이 끝나지 않은 표본은 정답을 0으로 채우지 않습니다.

## 이어서 할 작업

1. 원본 구조를 확인하고 정제 규칙을 결정합니다.
2. 고객별·월별 거래와 기준일별 고객 상태를 만듭니다.
3. 분류·회귀 정답과 군집 입력을 구성합니다.
4. 학습·검증·평가 기간을 정하고 각 기간에 사용할 입력을 확정합니다.

기존 [Synchrony 실험 코드](../../src/experiments/synchrony/README.md)에 원본 로드와 월별 스냅샷 생성 코드가 있습니다. 시작 노트북은 그중 `read_source`를 재사용해 날짜 변환, 고객·거래 ID 중복, 고객 연결을 검사합니다. 월별 특징과 모델 학습은 이후 작업에서 연결합니다.
