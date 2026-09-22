# 모델 코드

노트북의 분석 내용을 실행 가능한 Python 코드로 분리한 디렉터리입니다.
각 파일은 다른 파일에 의존하지 않고 독립적으로 실행할 수 있습니다.

## 파일 구성

| 파일 | 문제 유형 | 타깃 또는 기준 | 모델 |
|---|---|---|---|
| `classification.py` | 분류 | `Target` | Logistic Regression, Random Forest, XGBoost |
| `regression.py` | 회귀 | `Total_Trans_Ct` | Linear Regression, Random Forest, XGBoost |
| `clustering.py` | 군집 | 5개 행동 변수 | K-means (`k=3`) |

## 코드 읽는 순서

모든 파일은 다음과 같은 순서로 구성되어 있습니다.

1. 기본 경로와 설정값
2. 데이터 로드 함수
3. 전처리 또는 평가 함수
4. `main()` 학습 과정
5. 모델과 결과 저장

복잡한 추상화 대신 각 파일에서 전체 학습 흐름을 한 번에 확인할 수 있도록
일부 전처리 코드를 의도적으로 반복했습니다.

## 실행 방법

프로젝트 루트에서 가상환경을 활성화한 뒤 실행합니다.

```bash
source project_venv/bin/activate

python src/classification.py
python src/regression.py
python src/clustering.py
```

## 결과

- 학습 모델: `outputs/models/`
- 평가 지표와 군집 프로파일: `outputs/reports/`
- 분류·회귀 테스트 예측 결과: `outputs/reports/*_predictions.csv`

`outputs/`의 생성 파일은 `.gitignore`에 의해 Git에서 제외됩니다.
