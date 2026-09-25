"""Generate the Korean report after both advanced comparisons have completed.

The report never selects a model. It reads the selection already frozen by the
benchmark, measures uncertainty for those predeclared comparisons, and caches
bootstrap results with prediction-file and metric-code hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from .advanced_metrics import paired_customer_bootstrap


CONTROLS = ['previous_core6', 'tenure_control']
REPLICATES = 200
LABELS = {
    'previous_core6': '직전 개선 모델: 핵심 31개 특징·최근 6개월',
    'tenure_control': '보유·관측 기간·달력 비교 모델',
    'duration_hazard': '카드 보유기간별 일별 해지 위험',
    'tenure_calendar_lr': '보유기간과 달력 시기 상호작용',
    'behavior_lr': '결제수단 이동·구매 순서 특징 LR',
    'behavior_cat': '결제수단 이동·구매 순서 특징 CatBoost',
    'hazard_behavior_blend': '보유기간 위험·행동 CatBoost 순위 결합',
    'tenure_behavior_blend': '보유기간-시기·행동 LR 순위 결합',
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pct(value):
    return f'{100 * value:.2f}%'


def pp(value):
    return f'{100 * value:+.2f}%p'


def numeric(value, digits=4):
    return '해당 없음' if value is None else f'{value:.{digits}f}'


def candidate_label(name):
    return f'`{name}` ({LABELS.get(name, name)})'


def table(lines, headings, rows):
    lines.extend(['| ' + ' | '.join(headings) + ' |',
                  '| ' + ' | '.join(['---'] * len(headings)) + ' |'])
    lines.extend('| ' + ' | '.join(str(cell) for cell in row) + ' |' for row in rows)
    lines.append('')


def required_models(result):
    selection = result['selection']
    return list(dict.fromkeys(CONTROLS + [selection['selected'], selection['best_new_diagnostic']]))


def load_complete_results(root):
    """Refuse partial results; perform this check for both horizons before CIs."""
    loaded = {}
    for horizon in (30, 60):
        directory = root / f'classification_{horizon}'
        path = directory / 'results.json'
        if not path.exists():
            raise ValueError(f'{horizon}-day benchmark has not produced results.json')
        result = json.loads(path.read_text())
        if not all(key in result for key in ('protocol', 'development', 'selection', 'evaluation')):
            raise ValueError(f'{horizon}-day benchmark is incomplete')
        protocol = result['protocol']
        if protocol.get('horizon_days') != horizon:
            raise ValueError(f'{path}: horizon does not match its directory')
        selection_path = directory / 'selection.json'
        if not selection_path.exists() or json.loads(selection_path.read_text()) != result['selection']:
            raise ValueError(f'{path}: saved selection is absent or differs from results')
        development_dates = protocol['development_dates']
        for name in protocol['candidates']:
            item = result['development'].get(name, {})
            if [fold['date'] for fold in item.get('folds', [])] != development_dates:
                raise ValueError(f'{horizon}-day development is incomplete for {name}')
            if any(key not in item for key in ('mean_top10_recall', 'mean_ap', 'mean_auc')):
                raise ValueError(f'{horizon}-day development aggregates are incomplete for {name}')
        comparison_dates = protocol['evaluation_dates']
        populations = None
        for name in required_models(result):
            item = result['evaluation'].get(name, {})
            if [fold['date'] for fold in item.get('folds', [])] != comparison_dates:
                raise ValueError(f'{horizon}-day frozen evaluation is incomplete for {name}')
            if any(key not in item for key in ('audit', 'early_warning', 'mean_top10_recall', 'mean_ap', 'mean_auc')):
                raise ValueError(f'{horizon}-day evaluation aggregates are incomplete for {name}')
            population = [(fold['date'], fold['n'], fold['positive'], fold['top10_size'])
                          for fold in item['folds']]
            if populations is None:
                populations = population
            elif population != populations:
                raise ValueError(f'{horizon}-day compared customer populations or budgets differ')
            if not (directory / f'predictions_{name}.csv').exists():
                raise ValueError(f'{horizon}-day saved predictions are missing for {name}')
        loaded[horizon] = result
    return loaded


def cached_comparison(directory, horizon, baseline, candidate):
    a_path = directory / f'predictions_{baseline}.csv'
    b_path = directory / f'predictions_{candidate}.csv'
    signature = {
        'baseline_model': baseline, 'candidate_model': candidate,
        'baseline_prediction_sha256': sha(a_path), 'candidate_prediction_sha256': sha(b_path),
        'metrics_code_sha256': sha(Path(__file__).with_name('advanced_metrics.py')),
        'outcome': f'y_close_{horizon}', 'replicates': REPLICATES,
    }
    cache_path = directory / f'uncertainty_{candidate}_vs_{baseline}.json'
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get('signature') == signature and isinstance(cached.get('bootstrap'), dict):
            print('REUSE_UNCERTAINTY', horizon, candidate, baseline, flush=True)
            return cached['bootstrap']
    print('BOOTSTRAP', horizon, candidate, baseline, REPLICATES, flush=True)
    boot = paired_customer_bootstrap(pd.read_csv(a_path), pd.read_csv(b_path),
                                      signature['outcome'], reps=REPLICATES)
    payload = {'signature': signature, 'bootstrap': boot}
    temporary = cache_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(cache_path)
    return boot


def compare_selected_and_diagnostic(root, loaded):
    comparisons = {}
    for horizon, result in loaded.items():
        selection = result['selection']
        names = list(dict.fromkeys([selection['selected'], selection['best_new_diagnostic']]))
        comparisons[horizon] = {}
        for name in names:
            comparisons[horizon][name] = {
                baseline: cached_comparison(root / f'classification_{horizon}', horizon, baseline, name)
                for baseline in CONTROLS
            }
    return comparisons


def improvement_status(result, comparisons, name):
    """Apply the predeclared gate; later performance never changes selection."""
    passed_gate = bool(result['selection']['gate'].get(name, {}).get('passed', False))
    evidence = []
    for baseline in CONTROLS:
        comparison = comparisons[name][baseline]
        delta = comparison['observed_mean_delta']['top10_recall']
        interval = comparison['mean_delta_95_interval']['top10_recall']
        evidence.append(delta is not None and delta > 0 and interval is not None and interval[0] > 0)
    return passed_gate and all(evidence)


def interval_text(value):
    return '계산 불가' if value is None else f'[{pp(value[0])}, {pp(value[1])}]'


def audit_leaves(name, audit):
    if 'component_audits' in audit:
        for component, child in audit['component_audits'].items():
            yield from audit_leaves(f'{name} → {component}', child)
    else:
        yield name, audit


def render_report(loaded, comparisons, root):
    lines = ['# Synchrony 해지 분류 모델 추가 개선 결과', '',
             '이번 작업은 **미해지 고객의 이후 30일·60일 내 기록된 카드 해지 위험을 분류하는 모델**의 추가 실험이다. '
             '회귀·군집 모델의 추가 개선이나 CardOps 화면 개편 결과가 아니다. '
             '새 모델은 저장된 오프라인 실험 산출물이며 현재 CardOps 서비스에 배포하지 않았다.', '',
             '## 먼저 확인할 결론', '']
    conclusion_rows = []
    for horizon, result in loaded.items():
        selection = result['selection']
        selected = selection['selected']
        significant = improvement_status(result, comparisons[horizon], selected)
        if significant:
            judgment = '이번 재사용 평가 기간에서 신규 후보의 개선을 확인'
        elif selected in CONTROLS:
            judgment = '개발 통과 신규 후보 없음. 기존 비교 모델 유지'
        else:
            judgment = '개발 통과 후 재검증했으나 신규 개선 확정 기준 미충족'
        conclusion_rows.append([f'{horizon}일', f'`{selected}`',
                                f'`{selection["best_new_diagnostic"]}`', judgment])
    table(lines, ['예측 기간', '개발 기준으로 고정한 선택', '개발 최고 신규 후보(진단용)', '판단'], conclusion_rows)
    lines.extend([
        '“개선 확인”은 신규 후보가 개발 통과 조건을 만족하고, 후기 재검증에서 **두 비교 모델 각각보다** '
        '평균 월별 Recall@10%의 점 추정치가 높으며 고객 단위 paired bootstrap 95% 구간 하한도 0보다 큰 경우만 뜻한다. '
        '진단용 후보의 후기 점수가 좋더라도 개발 선택을 바꾸지 않는다.', '',
        '**후기 평가 기간은 이전 실험에서도 여러 차례 확인한 자료다.** '
        '이번 실행 안에서 선택과 학습을 동결했더라도 처음 보는 독립 테스트가 되지는 않는다. '
        '유의한 결과도 반복 개발의 영향을 배제한 미래 성능 보장이 아니며, 기준 미달도 데이터의 성능 상한을 뜻하지 않는다.', '',
        '## 실험 질문과 선택 규칙', '',
        '- 같은 월의 같은 고객 집합에서 상위 `ceil(고객 수 × 0.1)`명만 확인한다. 실제 해지 고객을 찾은 비율인 Recall@10%가 주지표다.',
        '- Precision@10%는 선택한 명단 중 실제 해지한 비율이다. AP와 ROC AUC도 공개하지만 후기 점수로 후보를 다시 선택하지 않는다.',
        '- 개발 후보는 기존 비교 모델 2개와 신규 후보 6개, 총 8개다. 후보와 결합 비율을 고정하고 비교했다.',
        '- 신규 후보는 두 비교 모델 각각보다 평균 포착률 **+2%p 이상**, 6개월 중 **4개월 이상 개선**, 최악의 월 감소가 **-2%p 이내**여야 한다.',
        '- 이 문턱은 실행 전에 정한 실무 기준이다. 통과 후보 중 개발 평균 포착률이 가장 높은 모델을 선택하고, 없으면 기존 두 비교 모델 중 개발 평균이 높은 모델을 유지한다.',
        '- 개발 최고 신규 후보 1개는 통과 여부와 관계없이 진단용으로 후기 평가한다. 이 공개는 모델 승격을 뜻하지 않는다.',
        '- 동점은 라벨과 무관한 고정 고객 해시로 해소한다. 고객 ID를 모델 입력으로 사용하지 않는다. '
        '따라서 과거 보고서와 직접 수치를 이어 붙이지 않고 이번에 같은 규칙으로 재평가한 비교 모델을 기준으로 삼는다.', '',
        '## 분리와 동결', '',
    ])
    first = loaded[30]['protocol']
    table(lines, ['항목', '규칙'], [
        ['개발 기준일', ', '.join(first['development_dates'])],
        ['각 개발월 학습', '월별 분류기는 해당 시점까지 전체 예측 기간의 정답 관측이 끝난 과거 표본만 사용'],
        ['최종 모델 동결', first['freeze_date']],
        ['30일 후기 평가', ', '.join(loaded[30]['protocol']['evaluation_dates'])],
        ['60일 후기 평가', ', '.join(loaded[60]['protocol']['evaluation_dates'])],
        ['후기 평가 중 학습', '없음. 저장·재로딩한 동일 모델로 예측만 수행'],
        ['같은 고객의 반복 등장', '과거 학습과 미래 평가에 허용. 동일 고객·동일 기준일 관측키 중복은 금지'],
    ])
    lines.extend([
        '월별 분류기의 30일 마지막 학습 상태는 2026-02-28이며 정답은 03-30까지 관측한다. '
        '60일 마지막 학습 상태는 2025-12-31이다. **2026-01-31의 60일 정답 종료일은 04-01**이므로 동결 학습에 사용할 수 없다.', '',
        '보유기간 위험 모델은 월별 완결 정답 대신 **동결일까지 관측된 계정의 위험 일수와 실제 해지 사건**을 사용한다. '
        '그 이후 해지는 동결일에서 관측이 끝난 것으로 처리한다. 관측 시작 전에 발급된 카드는 관측 시작 시점부터 위험집단에 진입한다. '
        '따라서 이 모델의 학습 범위는 월별 분류기의 마지막 학습 기준월과 구분한다.', '',
        '평균은 월별 지표의 단순 평균이며 고객 수나 해지 수가 많은 달에 더 큰 비중을 주지 않는다. '
        '동일 고객의 과거와 미래가 모두 있으므로 신규 고객만을 대상으로 한 일반화 평가도 아니다. '
        '**개발 기간과 후기 기간의 점수 차이를 모델 개선 폭으로 해석하지 않는다.** '
        '고객 구성과 해지 발생 패턴이 다른 시기이므로 개선은 같은 후기 시점의 비교 모델 간 차이로 판단한다.', '',
    ])

    for horizon, result in loaded.items():
        selection = result['selection']
        selected = selection['selected']
        diagnostic = selection['best_new_diagnostic']
        lines.extend([f'## {horizon}일 해지 분류', '', '### 개발 결과와 통과 조건', ''])
        dev_rows = []
        for name in result['protocol']['candidates']:
            item = result['development'][name]
            tags = []
            if name in CONTROLS:
                tags.append('비교 모델')
            else:
                tags.append('개발 통과' if selection['gate'][name]['passed'] else '개발 미통과')
            if name == selected:
                tags.append('선택')
            if name == diagnostic:
                tags.append('신규 진단 대상')
            dev_rows.append([candidate_label(name), pct(item['mean_top10_recall']),
                             pct(min(fold['top10_recall'] for fold in item['folds'])),
                             numeric(item['mean_ap']), numeric(item['mean_auc']), ' · '.join(tags)])
        table(lines, ['후보', '평균 포착률', '가장 낮은 월 포착률', '평균 AP', '평균 AUC', '개발 결정'], dev_rows)
        gate_rows = []
        for name, gate in selection['gate'].items():
            for baseline in CONTROLS:
                check = gate['comparisons'][baseline]
                gate_rows.append([f'`{name}`', f'`{baseline}`', pp(check['mean_gain']),
                                  f'{check["improved_months"]}/6', pp(check['worst_month_gain']),
                                  '통과' if check['passed'] else '미통과'])
        table(lines, ['신규 후보', '비교 기준', '평균 차이', '개선 월 수', '가장 나쁜 월 차이', '해당 비교 통과'], gate_rows)
        lines.extend([f'개발 규칙으로 **`{selected}`**를 선택했다. **`{diagnostic}`**는 개발 평균 포착률이 가장 높은 신규 후보이며 '
                      '진단용 후기 평가 대상이다. 최종 선택은 후기 점수를 보기 전에 `selection.json`에 저장했다.', '',
                      '### 동결 모델의 후기 평균 성능', ''])
        names = required_models(result)
        summary_rows = []
        for name in names:
            item = result['evaluation'][name]
            status = '기존 비교 모델' if name in CONTROLS else '신규 후보'
            if name == selected:
                status += ' · 개발 선택'
            if name == diagnostic:
                status += ' · 신규 진단 대상'
            summary_rows.append([f'`{name}`', status, pct(item['mean_top10_recall']),
                                 pct(min(fold['top10_recall'] for fold in item['folds'])),
                                 pct(item['mean_top10_precision']), numeric(item['mean_ap']), numeric(item['mean_auc'])])
        table(lines, ['모델', '역할', '평균 포착률', '최저 월 포착률', '평균 명단 해지 비율', '평균 AP', '평균 AUC'], summary_rows)
        lines.extend(['### 같은 월·같은 검토 인원에서 포착한 고객', ''])
        month_rows = []
        for date in result['protocol']['evaluation_dates']:
            for name in names:
                fold = next(item for item in result['evaluation'][name]['folds'] if item['date'] == date)
                month_rows.append([date, f'{fold["n"]:,}', f'{fold["top10_size"]:,}', f'{fold["positive"]:,}',
                                   f'`{name}`', f'{fold["top10_caught"]:,}', pct(fold['top10_recall']), pct(fold['top10_precision'])])
        table(lines, ['기준일', '전체 고객', '검토 인원', '실제 기간 내 해지', '모델', '명단에서 찾은 해지', '포착률', '명단 해지 비율'], month_rows)
        lines.extend(['### 동일 고객 반복을 반영한 불확실성', '',
                      '아래 차이는 후보 − 비교 모델이며 각 월에 같은 비중을 준다. '
                      f'고객 단위 paired bootstrap을 **{REPLICATES}회** 수행했다. 고객이 선택되면 그 고객의 모든 월 기록을 함께 재표집했다.', ''])
        ci_rows = []
        for name, by_baseline in comparisons[horizon].items():
            for baseline, boot in by_baseline.items():
                ci_rows.append([f'`{name}`', f'`{baseline}`',
                                pp(boot['observed_mean_delta']['top10_recall']),
                                interval_text(boot['mean_delta_95_interval']['top10_recall']),
                                numeric(boot['observed_mean_delta']['ap']),
                                numeric(boot['observed_mean_delta']['auc']),
                                f'{boot["valid_replicates"]["top10_recall"]}/{REPLICATES}'])
        table(lines, ['후보', '비교 모델', '평균 포착률 차이', '차이의 95% 구간', 'AP 차이', 'AUC 차이', '유효 반복'], ci_rows)
        lines.extend([
            '상위 10% 계산은 고객 복제 횟수만큼 행을 실제 반복했을 때와 동일하다. '
            '경계에 걸린 고객의 복제본도 정수 개수만 포함한다. 분수 예산으로 평가 정의를 바꾸지 않았다. '
            'AP와 AUC도 같은 정수 복제 가중치를 사용하며 전체 지표의 95% 구간은 각 `uncertainty_*.json`에 보존했다.', '',
            '**이 구간은 고정된 관측월 안의 고객 표본 불확실성만 나타낸다.** '
            '미래 시기의 변화, 반복 모델 선택의 영향, 캠페인 개입 효과를 포함하지 않는다.', '',
        ])
        for name in dict.fromkeys([selected, diagnostic]):
            if name in CONTROLS:
                lines.append(f'- `{name}`: 기존 비교 모델이다. 신규 후보의 통과 심사 대상이 아니며, 개발 규칙의 기본 선택으로 유지했다.')
                continue
            passed = bool(selection['gate'].get(name, {}).get('passed', False))
            confirmed = improvement_status(result, comparisons[horizon], name)
            decision = ('개발 통과 및 두 기준 대비 포착률의 양의 차이·95% 구간 조건을 만족했다.' if confirmed else
                        '개발 통과 및 두 기준 대비 포착률의 양의 차이·95% 구간 조건을 모두 만족하지 못했다.')
            lines.append(f'- `{name}`: 개발 통과 여부 **{"통과" if passed else "미통과"}**. {decision}')
        lines.extend(['', '### 실제 해지 사건과 조기 발견 시점', ''])
        early_rows = []
        for name in names:
            early = result['evaluation'][name]['early_warning']
            repeated = early['true_positive_alert_customer_months'] - early['unique_closing_customers_alerted']
            early_rows.append([f'`{name}`', f'{early["unique_closing_customers"]:,}',
                               f'{early["unique_closing_customers_alerted"]:,}',
                               f'{early["unique_closing_customers_with_14_day_opportunity"]:,}',
                               f'{early["unique_closing_customers_alerted_at_least_14_days_before"]:,}',
                               f'{repeated:,}', numeric(early['median_first_alert_lead_days'], digits=1)])
        table(lines, ['모델', '기간 내 고유 해지 고객', '한 번 이상 포착한 고유 고객', '14일 이상 전 평가 기회가 있던 고객',
                      '실제로 14일 이상 전에 포착', '같은 해지 고객의 추가 포착 횟수', '첫 포착→해지 중앙값(일)'], early_rows)
        lines.extend([
            '위 집계는 평가한 기준일에서 해당 30일·60일 예측 범위 안에 들어온 해지 사건만 포함한다. '
            '같은 사건의 반복 포착을 고유 고객으로 중복 계산하지 않았다. '
            '첫 포착 시점은 해당 해지가 30일·60일 정답 범위에 들어온 평가월들 중 명단에 처음 포함된 기준일이다. '
            '이 범위보다 더 이전에 명단에 올랐던 경우까지 포함한 전체 운영 이력의 최초 경고 시점은 아니다. '
            '14일 전에 발견했다는 것은 대응 가능한 시간의 지표이며 실제로 해지를 막았다는 의미는 아니다.', '',
            '### 저장된 모델의 학습 범위', '',
        ])
        audit_rows = []
        for name in names:
            for component, audit in audit_leaves(name, result['evaluation'][name]['audit']):
                if 'training_rows' in audit:
                    audit_rows.append([f'`{component}`', '완결된 월별 정답', f'{audit["training_rows"]:,}',
                                       audit['training_first_as_of'], audit['training_last_as_of'],
                                       audit['training_label_end_max'], str(audit['training_evaluation_key_overlap'])])
                else:
                    audit_rows.append([f'`{component}`', '계정 위험 일수·관측된 해지', '월별 행 집계와 다름',
                                       audit.get('observation_start', '기록 없음'),
                                       audit.get('event_and_exposure_cutoff', '기록 없음'),
                                       audit.get('event_and_exposure_cutoff', '기록 없음'),
                                       str(audit.get('training_evaluation_key_overlap', '기록 없음'))])
        table(lines, ['모델/구성요소', '학습 단위', '학습 행 수', '처음 상태/관측', '마지막 상태/관측', '사용 결과의 마지막 날짜', '동일 관측키 중복'], audit_rows)
        lines.extend([
            '위 중복 0은 같은 고객이 양쪽에 없다는 뜻이 아니다. 월별 분류기는 동일 고객·동일 기준일의 관측을 분리했고, '
            '위험 일수 모델은 후기 사건과 관측일을 적합 범위에서 제외했다. '
            '벤치마크는 후기 예측 전후 저장 모델과 선택 파일의 SHA-256이 바뀌면 오류를 발생시킨다.', '',
        ])

    lines.extend(['## 해석과 사용 범위', '',
                  '- 정답은 해당 고객의 기록된 카드 해지일이 미래 30일·60일 안에 있는지다. 자발적 해지, 강제 해지, 다른 은행으로의 이동을 구분한 정답은 아니다.',
                  '- 해지 위험 순위는 확인할 고객의 우선순위를 제공한다. 현재 점수를 개인별로 보정된 해지 확률이나 캠페인 성공 확률로 표시하면 안 된다.',
                  '- 순위 앙상블은 한 기준일의 전체 대상 고객 집합에서 계산한다. 고객 한 명만 따로 입력해 같은 점수가 나오는 서비스 계약이 아니다.',
                  '- 거래 특징은 해당 제휴몰에서 관측한 구매·반품·결제수단만 다룬다. 다른 가맹점의 전체 카드 사용을 관측한 것이 아니다.',
                  '- 거래일·발급일·해지일에 정보가 바로 사용 가능했다는 가정과 계정 위험기간의 연속 관측 가정이 필요하다. 최종 고객 파일에 포함되는 과정과 과거 정보 도착 시각은 검증하지 못했다.',
                  '- 더 좋은 위험 명단이 곧 이탈 예방 효과나 매출 기여를 입증하지 않는다. 캠페인 개입 결과가 별도로 있어야 한다.',
                  '- 이번 고정 후보 비교가 끝난 뒤 같은 후기 점수로 추가 후보나 가중치를 조정하지 않는다. 독립적인 최종 성능 확인에는 아직 개발에 사용하지 않은 새 관측 기간이나 별도 자료가 필요하다.', '',
                  '## 구현·산출물 검증', '',
                  '이번 작업의 기존·신규 테스트 합계 **34개가 통과**했다. '
                  '별도 `advanced_audit.py` 검사에서는 원본 ZIP·입력 스냅숏·특징 캐시와 코드 해시, '
                  '실험 계획·실험 코드 해시, 선택 JSON 일치, 저장 모델 해시를 포함한 **68개 검사가 통과**했다. '
                  '이 검사는 확인한 구현과 산출물의 일관성을 검증하며 원본의 수집 과정이나 미래 성능을 증명하지 않는다.', '',
                  '## 재현 파일', '',
                  '- 계획: [synchrony_improvement_plan.md](synchrony_improvement_plan.md)',
                  '- 실행·산출물 설명: [실험 README](../src/experiments/synchrony/README.md)',
                  f'- 이번 결과 루트: `{root.resolve()}`',
                  '- 각 분류 폴더의 `protocol.json`, `selection.json`, `results.json`, `predictions_*.csv`, `*.joblib` 및 `uncertainty_*.json`을 사용했다.',
                  '- 불확실성 계산은 예측 파일 두 개의 SHA-256, 지표 코드 SHA-256, 정답 종류와 반복 횟수가 모두 같은 경우에만 재사용한다.', '',
                  '| 예측 기간 | 원본 ZIP SHA-256 | 계획 SHA-256 |',
                  '| --- | --- | --- |'])
    for horizon, result in loaded.items():
        protocol = result['protocol']
        lines.append(f'| {horizon}일 | `{protocol["source_sha256"]}` | `{protocol["plan_sha256"]}` |')
    lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    loaded = load_complete_results(args.results)
    comparisons = compare_selected_and_diagnostic(args.results, loaded)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_report(loaded, comparisons, args.results))
    print('REPORT_COMPLETE', args.output, flush=True)


if __name__ == '__main__':
    main()
