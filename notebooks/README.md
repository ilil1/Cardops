# 데이터셋별 분석 노트북

전처리·EDA·모델 실험을 데이터셋별 디렉터리에서 관리합니다.

```text
notebooks/
├── BankChurners/                 # 기존 전처리·EDA·분류·회귀·군집 노트북 14개
└── Synchrony/
    ├── README.md                # 작업 순서와 데이터 경로
    └── 01_data_load_clean.ipynb  # 원본 로드·날짜 변환·기본 구조 확인
```

- [BankChurners](BankChurners/README.md): 기존 분석 기록과 실행 방법
- [Synchrony](Synchrony/README.md): 새 데이터 전처리를 시작하는 작업 공간

원본은 `data/raw/`, 정제본은 `data/processed/`, 학습·평가 산출물은 `outputs/`에 저장합니다. 노트북 디렉터리에는 분석 코드와 설명을 둡니다.
