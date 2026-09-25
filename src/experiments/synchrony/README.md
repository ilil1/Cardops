# Synchrony 후보 데이터 모델 개선 실험

기존 CardOps API 모델과 독립된 오프라인 실험입니다. 원본 데이터 및 모델 파일은 Git에 포함하지 않습니다. 저장된 모델은 재사용할 수 있지만 API에 자동으로 배포되지 않습니다.

## 입력과 재실행

원본: [참가자 공개 저장소](https://github.com/chawanaryan19/Customer-and-Credit-Card-Analysis---Declining-Share-of-Wallet)의 `Datasets.zip`.

이번 실험 원본 SHA-256: `bf66d162bbbf564e93c45623d5a3f89606acb18e6accf3bef157ef1652f4b5cf`.

```bash
python -m pip install -r src/experiments/synchrony/requirements.txt
python -m src.experiments.synchrony.data --zip /path/to/Datasets.zip --output outputs/synchrony_data
python -m src.experiments.synchrony.benchmark --snapshots outputs/synchrony_data/snapshots.pkl --features outputs/synchrony_data/features.json --output outputs/synchrony_tuning
python -m src.experiments.synchrony.transfer --snapshots outputs/synchrony_data/snapshots.pkl --features outputs/synchrony_data/features.json --selection outputs/synchrony_tuning/classification_30/results.json --output outputs/synchrony_tuning
python -m unittest src.experiments.synchrony.test_protocol
```

`snapshot()`은 기준일까지 발급되고 아직 해지되지 않은 고객만 포함합니다. 거래 입력은 기준일까지 관측한 기록만 사용하고, 미래 해지와 다음 달 구매는 별도 정답 컬럼에 둡니다. 관측 기간이 부족하면 미래 정답을 0으로 채우지 않습니다. 반품 금액은 별도 특징이며 구매건수/구매금액 정답에 합산하지 않습니다.

## 비교 규칙

- 기존 210개 특징의 로지스틱 분류 모델을 기준으로 고정합니다.
- 고객 ID, 해지일, 미래 정답, 최종 고객 테이블의 나이·성별·한도·APR·멤버십은 모델 입력에서 제외합니다.
- 카드 보유 기간과 거래 관측 기간, 거래 기회 대비 활동량, 변화율, spline 변환, CatBoost, 최근 6개월 학습을 비교합니다.
- 개발 시점: 2025-10-31, 2025-12-31, 2026-02-28. 세 시점의 평균 Average Precision으로 모델을 선택합니다.
- 이후 2026년 3~6월의 네 기준일에서 기존 모델과 선택된 모델을 비교합니다. 매 기준일에 정답 관측이 끝난 과거 표본만 학습합니다.
- 이 기간들은 이전 실험에서도 일부 확인했으므로 **완전히 독립된 테스트가 아닌 반복 시간순 검증**입니다. 결과를 확인한 후 이 기간 점수를 기준으로 모델을 다시 선택하지 않습니다.
- 같은 고객이 여러 달 등장하는 사용 상황을 평가합니다. 신규 고객에 대한 별도 일반화 성능은 아닙니다.
- AP와 AUC에 더해 위험 점수 상위 10%에 포함된 실제 해지 고객 수와 포착률을 기록합니다. 점수는 보정된 개인별 해지 확률이 아닙니다.

## 산출물

`outputs/synchrony_tuning/classification_30/`에 다음을 저장합니다.

- `protocol.json`: 평가 전 고정한 후보·기간·선택 기준·코드 해시
- `results.json`: 모든 후보의 개발 성능과 선택 모델의 이후 기간 성능
- `predictions_*.csv`: 고객별 점수와 비교용 정답
- `*.joblib`: 마지막 평가 기준일에 이용 가능한 정답으로 학습한 모델과 입력 계약

저장 모델 사용 시 이 저장소의 모듈을 import할 수 있어야 합니다. `models.prepare_features(snapshot, bundle['original_features'])`로 입력을 만든 뒤 `bundle['model'].predict_proba(features)[:, 1]`을 호출합니다. 본인이 만든 신뢰할 수 있는 joblib/pickle 파일만 읽습니다.

60일 비교는 `classification_60_transfer/`에 별도로 저장합니다. 30일 개발 구간에서 선택한 방법을 그대로 적용하며, 이전 60일 HGB 모델과 같은 평가 시점에서 비교합니다. 60일 결과를 보고 추가 튜닝하지 않습니다.

```bash
python -m src.experiments.synchrony.predict --model outputs/synchrony_tuning/classification_60_transfer/lr_core_recent6.joblib --snapshots outputs/synchrony_data/snapshots.pkl --as-of 2026-05-31 --output outputs/synchrony_tuning/review_candidates_60d.csv
python -m src.experiments.synchrony.uncertainty --baseline outputs/synchrony_tuning/classification_60_transfer/predictions_previous_hgb60.csv --candidate outputs/synchrony_tuning/classification_60_transfer/predictions_lr_core_recent6.csv --horizon 60 --output outputs/synchrony_tuning/classification_60_transfer/uncertainty.json
```

`predict`는 학습 당시보다 과거의 기준일에 모델을 적용하면 오류를 냅니다. 결과에는 고객 ID, 기준일, 예측 기간, 순위 점수, 우선순위와 상위 10% 여부를 저장합니다. `uncertainty`는 같은 고객의 여러 시점 기록을 함께 재표집하여 중복 고객과 겹치는 60일 정답 기간을 고려합니다. 이 구간은 관측한 달 내 표본 불확실성이며 미래 시기 변화나 반복 튜닝의 영향을 포함하지 않습니다.

원본의 거래 누락이 없다는 가정, 거래일에 기록이 이용 가능하다는 가정이 필요합니다. 데이터는 제휴몰에서의 구매를 다루며 카드 전체 가맹점 이용 내역이 아닙니다. 데이터 사용·재배포 권한은 별도 확인 대상입니다.

참고 구현 문서: [CatBoostClassifier](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier), [SplineTransformer](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.SplineTransformer.html).

## 고정 모델로 다시 평가하기

`strict_benchmark`는 2026-03-30에 모델을 한 번 학습하고 저장한 뒤, 이후 모든 평가 시점에 동일한 모델로 예측만 합니다. 앞선 평가월의 정답을 뒤 평가월의 학습에 편입하지 않습니다. 개발 기준일은 2025-08-31·10-31·12-31로 고정하며 정답 관측 기간이 동결일을 넘으면 실행을 거부합니다.

```bash
python -m src.experiments.synchrony.strict_benchmark --snapshots outputs/synchrony_data/snapshots.pkl --features outputs/synchrony_data/features.json --output outputs/synchrony_strict --horizon 30
python -m src.experiments.synchrony.strict_benchmark --snapshots outputs/synchrony_data/snapshots.pkl --features outputs/synchrony_data/features.json --output outputs/synchrony_strict --horizon 60
python -m src.experiments.synchrony.strict_report --results outputs/synchrony_strict --output docs/synchrony_strict_evaluation.md
python -m unittest src.experiments.synchrony.test_protocol src.experiments.synchrony.test_strict_protocol
```

각 결과 폴더에는 실행 전 고정한 규칙, 개발 시점별 점수, 평가 전 선택 결과, 동결 모델, 학습 범위·평가행 중복 점검, 모델 파일 해시, 고객별 평가 점수를 저장합니다. `predict`는 이 동결 모델의 확장 특징 처리도 지원합니다.

이전에 확인했던 평가 기간이라는 사실은 그대로입니다. **고정 분할을 새로 만들었다고 독립 테스트가 되지는 않습니다.** 같은 고객의 과거/미래 관측은 허용하지만 같은 고객·같은 기준일 행은 학습과 평가에서 완전히 분리합니다.

기존 `benchmark --horizon 60`을 직접 실행할 때에도 개발 정답이 첫 확인일 전에 끝나도록 개발 날짜를 제한합니다. 이 수정은 과거 결과 파일을 변경하지 않습니다.

## 업무 기준을 고정한 추가 개선 실험

[사전 계획](../../../docs/synchrony_improvement_plan.md)에 따라, 과거 6개 월의 상위 10% 포착률로 후보를 선택합니다. 기존 두 비교 모델, 보유기간 위험, 보유기간과 달력시간의 상호작용, 결제수단 변화 특징, 고정 순위 결합을 비교합니다. 원본에서 새 특징 60개를 생성하고 그중 계획에 고정한 18개만 모델 입력으로 사용합니다.

```bash
python -m src.experiments.synchrony.advanced_cache --source-zip /path/to/Datasets.zip --snapshots outputs/synchrony_data/snapshots.pkl --output outputs/synchrony_data/advanced_features.pkl
python -m src.experiments.synchrony.advanced_benchmark --source-zip /path/to/Datasets.zip --snapshots outputs/synchrony_data/snapshots.pkl --features outputs/synchrony_data/features.json --additional outputs/synchrony_data/advanced_features.pkl --output outputs/synchrony_advanced --horizon 30
python -m src.experiments.synchrony.advanced_benchmark --source-zip /path/to/Datasets.zip --snapshots outputs/synchrony_data/snapshots.pkl --features outputs/synchrony_data/features.json --additional outputs/synchrony_data/advanced_features.pkl --output outputs/synchrony_advanced --horizon 60
python -m src.experiments.synchrony.advanced_audit --cache-metadata outputs/synchrony_data/advanced_features.json --results outputs/synchrony_advanced
python -m src.experiments.synchrony.advanced_report --results outputs/synchrony_advanced --output docs/synchrony_advanced_evaluation.md
python -m unittest discover -s src/experiments/synchrony -t . -p 'test_*.py'
```

동결일·후기 재검증 기간은 `strict_benchmark`와 같습니다. 후기 지표를 보기 전에 `selection.json`을 저장합니다. 새 후보는 두 비교 모델 각각보다 개발 평균 +2%p, 6개월 중 4개월 이상 개선, 최악의 달 -2%p 이내라는 기준을 모두 만족해야 선택됩니다. 통과하지 못해도 개발 점수가 가장 높은 신규 후보 1개는 진단용으로 후기 성능을 공개하며, 그 결과로 다시 선택하지 않습니다.

`advanced` 모델은 입력 구조와 결합 방식이 달라 기존 `predict` CLI로 읽지 않습니다. 다음 함수를 사용합니다.

```python
import joblib
from src.experiments.synchrony.advanced_models import prepare_advanced_features, predict_bundle

bundle = joblib.load(model_path)
# snapshot_frame과 additional_frame은 하나의 같은 기준일, 전체 대상 고객 집단입니다.
# 기준일은 bundle['as_of_date'] 이후여야 합니다.
x = prepare_advanced_features(snapshot_frame, bundle['original_features'], additional_frame)
scores = predict_bundle(bundle, x, snapshot_frame.customer_id)
```

순위 결합은 해당 기준일의 고객 집단에 따라 달라집니다. 한 고객씩 따로 호출하는 실시간 확률 API로 사용하지 않습니다. 모든 점수는 비교를 위한 우선순위이며 개인별 해지 확률 보정을 검증하지 않았습니다. 위험집단 모델은 고객 파일이 과거의 전체 대상 계정을 포함한다는 추가 가정이 필요합니다.

결과물은 `outputs/synchrony_advanced/classification_30/`와 `classification_60/`에 저장합니다. 고객 단위 bootstrap, 같은 고객의 여러 경보를 합친 실제 해지 고객 수, 최소 14일 전에 발견한 고객 수도 기록합니다. 통계 구간은 이미 확인한 달 안에서의 불확실성만 반영하며, 새 시기의 성능이나 반복 실험으로 인한 선택 편향을 해소하지 않습니다.

`advanced_audit`는 캐시 메타데이터의 원본·스냅샷·특징 생성 코드 해시와 실제 입력을 대조하고, 실험 당시 계획·코드·모델 파일의 변경 여부를 검사합니다. 감사 후 코드를 수정하면 해당 과거 실행의 해시 감사가 실패할 수 있으므로 원래 실행 버전을 보존해야 합니다. 결과 해석은 [추가 개선 보고서](../../../docs/synchrony_advanced_evaluation.md)를 참고합니다.
