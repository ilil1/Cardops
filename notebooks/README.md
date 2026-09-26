# 데이터셋별 분석 노트북

전처리·EDA·모델 실험을 데이터셋별 디렉터리에서 관리합니다.

```text
notebooks/
├── BankChurners/                 # 기존 전처리·EDA·분류·회귀·군집 노트북 14개
└── Synchrony/
    ├── README.md                # 작업 순서와 데이터 경로
    ├── 01_data_load_clean.ipynb  # 원본 로드·기본 품질·사전·결측·관측 기간 확인
    └── 02_eda.ipynb              # ABC 카드 보유·사용·미사용·해지 전 행동 탐색
```

- [BankChurners](BankChurners/README.md): 기존 분석 기록과 실행 방법
- [Synchrony](Synchrony/README.md): 기본 전처리와 EDA를 분리한 작업 공간. 02는 원본을 독립적으로 로드합니다.

원본은 `data/raw/`, 정제본은 `data/processed/`, 학습·평가 산출물은 `outputs/`에 저장합니다. 노트북 디렉터리에는 분석 코드와 설명을 둡니다.
