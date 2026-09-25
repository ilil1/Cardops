# BankChurners 분석 노트북

기존 BankChurners 노트북 14개를 모았습니다. 폴더 이동에 맞춰 데이터와 결과 파일의 상대 경로를 수정했습니다.

## 실행

저장소 루트에서 기존 Python 분석 환경을 활성화한 뒤 실행합니다.

```bash
python -m pip install -r requirements.txt
cd notebooks/BankChurners
jupyter lab
```

노트북 커널의 작업 디렉터리는 `notebooks/BankChurners/`를 기준으로 합니다.

## 기본 순서

1. `01_data_load_clean.ipynb`: 원본 로드와 정제
2. `02_eda.ipynb`: 고객 특성과 이탈 상태 탐색
3. `03_classification.ipynb`: 이탈 상태 분류
4. `04_regression.ipynb`: 거래건수 추정과 활동성 갭 분석
5. `05_clustering.ipynb`: 고객 행동 군집 분석

나머지 노트북은 추가 실험과 이전 작업 기록입니다. 기존 저장 출력은 당시 실행 결과입니다.

## 데이터와 결과 경로

- 원본: `../../data/raw/BankChurners.csv`
- 정제본: `../../data/processed/bankchurners_clean.csv`
- 회귀 갭 결과: `../../outputs/gap_result/gap_result_B.pkl`

갭 결과를 저장하기 전에 `outputs/gap_result/` 디렉터리가 있어야 합니다. `05_clustering(gap).ipynb`는 `04_regression_final.ipynb`에서 저장한 갭 결과를 읽습니다.

현재 서비스 모델의 학습 코드는 [`src/final/`](../../src/final/)에 있습니다. 데이터 해석 범위는 [데이터 전환 배경](../../docs/data_transition/README.md)을 참고합니다.
