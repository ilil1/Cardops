"""학습된 분류·회귀·군집 모델의 성능을 확인하는 Streamlit 대시보드.

실행:
    streamlit run dashboard/app.py
"""

from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from sklearn.metrics import roc_curve


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "outputs" / "reports"

MODEL_LABELS = {
    "logistic_regression": "Logistic Regression",
    "linear_regression": "Linear Regression",
    "random_forest": "Random Forest",
    "xgboost": "XGBoost",
}
CLASSIFICATION_MODEL_ORDER = [
    "Logistic Regression",
    "Random Forest",
    "XGBoost",
]
REGRESSION_MODEL_ORDER = [
    "Linear Regression",
    "Random Forest",
    "XGBoost",
]
DATASET_COLORS = {
    "Train": "#2563EB",
    "Test": "#F97316",
}
CLASSIFICATION_METRIC_LABELS = {
    "F1": "F1 점수",
    "Recall": "Recall (재현율)",
    "Precision": "Precision (정밀도)",
    "ROC_AUC": "ROC-AUC",
    "Accuracy": "Accuracy (정확도)",
}
REGRESSION_METRIC_LABELS = {
    "RMSE": "RMSE (평균 제곱근 오차)",
    "MAE": "MAE (평균 절대 오차)",
    "R2": "R² (결정계수)",
}


def read_report(filename: str, index_col: int | None = None) -> pd.DataFrame | None:
    """결과 CSV를 읽고, 파일이 없으면 None을 반환한다."""
    path = REPORT_DIR / filename
    if not path.exists():
        return None
    return pd.read_csv(path, index_col=index_col)


def display_model_names(data: pd.DataFrame) -> pd.DataFrame:
    """내부 모델 이름을 화면용 이름으로 변환한다."""
    result = data.copy()
    if "Model" in result.columns:
        result["Model"] = result["Model"].replace(MODEL_LABELS)
    return result


def show_missing_result(filename: str, command: str) -> None:
    """필요한 결과 파일이 없을 때 생성 방법을 안내한다."""
    st.warning(f"`outputs/reports/{filename}` 파일이 없습니다.")
    st.code(command, language="bash")


def classification_overfit_status(f1_gap: float, auc_gap: float) -> str:
    """Train과 Test 분류 성능 차이로 간단한 확인 상태를 만든다."""
    largest_gap = max(f1_gap, auc_gap)
    if largest_gap >= 0.10:
        return "확인 필요"
    if largest_gap >= 0.05:
        return "주의"
    return "큰 차이 없음"


def regression_overfit_status(r2_gap: float, rmse_increase: float) -> str:
    """Train과 Test 회귀 성능 차이로 간단한 확인 상태를 만든다."""
    if r2_gap >= 0.10 or rmse_increase >= 0.50:
        return "확인 필요"
    if r2_gap >= 0.05 or rmse_increase >= 0.20:
        return "주의"
    return "큰 차이 없음"


def make_classification_chart(
    data: pd.DataFrame,
    metric: str,
) -> alt.LayerChart:
    """Train/Test를 명확하게 구분한 분류 성능 막대그래프를 만든다."""
    chart_data = data[["Model", "Dataset", metric]].copy()
    dataset_order = ["Train", "Test"]

    base = alt.Chart(chart_data).encode(
        x=alt.X(
            "Model:N",
            title="모델",
            sort=CLASSIFICATION_MODEL_ORDER,
            axis=alt.Axis(labelAngle=0),
        ),
        xOffset=alt.XOffset("Dataset:N", sort=dataset_order),
        y=alt.Y(
            f"{metric}:Q",
            title=CLASSIFICATION_METRIC_LABELS[metric],
            scale=alt.Scale(domain=[0, 1.05]),
        ),
    )

    bars = base.mark_bar(
        size=38,
        cornerRadiusTopLeft=4,
        cornerRadiusTopRight=4,
    ).encode(
        color=alt.Color(
            "Dataset:N",
            title="데이터 구분",
            sort=dataset_order,
            scale=alt.Scale(
                domain=dataset_order,
                range=[DATASET_COLORS[name] for name in dataset_order],
            ),
            legend=alt.Legend(orient="top"),
        ),
        tooltip=[
            alt.Tooltip("Model:N", title="모델"),
            alt.Tooltip("Dataset:N", title="데이터"),
            alt.Tooltip(f"{metric}:Q", title="점수", format=".3f"),
        ],
    )

    labels = base.mark_text(
        dy=-9,
        color="#111827",
        fontSize=13,
        fontWeight="bold",
    ).encode(text=alt.Text(f"{metric}:Q", format=".3f"))

    return (bars + labels).properties(
        height=380,
        title=f"모델별 Train/Test {CLASSIFICATION_METRIC_LABELS[metric]}",
    )


def make_regression_chart(
    data: pd.DataFrame,
    metric: str,
) -> alt.LayerChart:
    """Train/Test를 명확하게 구분한 회귀 성능 막대그래프를 만든다."""
    chart_data = data[["Model", "Dataset", metric]].copy()
    dataset_order = ["Train", "Test"]

    if metric == "R2":
        minimum = min(0, chart_data[metric].min() - 0.05)
        maximum = max(1.05, chart_data[metric].max() + 0.05)
    else:
        minimum = 0
        maximum = chart_data[metric].max() * 1.18

    base = alt.Chart(chart_data).encode(
        x=alt.X(
            "Model:N",
            title="모델",
            sort=REGRESSION_MODEL_ORDER,
            axis=alt.Axis(labelAngle=0),
        ),
        xOffset=alt.XOffset("Dataset:N", sort=dataset_order),
        y=alt.Y(
            f"{metric}:Q",
            title=REGRESSION_METRIC_LABELS[metric],
            scale=alt.Scale(domain=[minimum, maximum]),
        ),
    )

    bars = base.mark_bar(
        size=38,
        cornerRadiusTopLeft=4,
        cornerRadiusTopRight=4,
    ).encode(
        color=alt.Color(
            "Dataset:N",
            title="데이터 구분",
            sort=dataset_order,
            scale=alt.Scale(
                domain=dataset_order,
                range=[DATASET_COLORS[name] for name in dataset_order],
            ),
            legend=alt.Legend(orient="top"),
        ),
        tooltip=[
            alt.Tooltip("Model:N", title="모델"),
            alt.Tooltip("Dataset:N", title="데이터"),
            alt.Tooltip(f"{metric}:Q", title="값", format=".3f"),
        ],
    )

    labels = base.mark_text(
        dy=-9,
        color="#111827",
        fontSize=13,
        fontWeight="bold",
    ).encode(text=alt.Text(f"{metric}:Q", format=".3f"))

    return (bars + labels).properties(
        height=380,
        title=f"모델별 Train/Test {REGRESSION_METRIC_LABELS[metric]}",
    )


def make_cluster_profile_chart(
    data: pd.DataFrame,
    value_column: str,
    y_title: str,
    color: str,
    percentage: bool = False,
) -> alt.LayerChart:
    """군집 라벨과 값을 읽기 쉽게 표시한 세로 막대그래프를 만든다."""
    chart_data = data[["Cluster", value_column]].copy()
    chart_data["Cluster_Label"] = chart_data["Cluster"].map(
        lambda number: f"군집 {int(number)}"
    )
    cluster_order = chart_data["Cluster_Label"].tolist()
    value_format = ".1%" if percentage else ",.0f"

    base = alt.Chart(chart_data).encode(
        x=alt.X(
            "Cluster_Label:N",
            title="군집",
            sort=cluster_order,
            axis=alt.Axis(labelAngle=0, labelPadding=8),
        ),
        y=alt.Y(
            f"{value_column}:Q",
            title=y_title,
            scale=alt.Scale(
                domain=[0, chart_data[value_column].max() * 1.18]
            ),
            axis=alt.Axis(format=".0%" if percentage else ",.0f"),
        ),
    )

    bars = base.mark_bar(
        size=72,
        color=color,
        cornerRadiusTopLeft=4,
        cornerRadiusTopRight=4,
    ).encode(
        tooltip=[
            alt.Tooltip("Cluster_Label:N", title="군집"),
            alt.Tooltip(
                f"{value_column}:Q",
                title=y_title,
                format=value_format,
            ),
        ]
    )
    labels = base.mark_text(
        dy=-9,
        color="#111827",
        fontSize=13,
        fontWeight="bold",
    ).encode(text=alt.Text(f"{value_column}:Q", format=value_format))

    return (bars + labels).properties(height=320)


st.set_page_config(
    page_title="고객 이탈 모델 성능 대시보드",
    page_icon="💳",
    layout="wide",
)

st.title("💳 고객 이탈 분석 모델 대시보드")
st.caption(
    "분류·회귀 모델의 Train/Test 결과와 군집 모델의 평가 결과를 비교합니다. "
    "표시된 수치는 현재 데이터의 단일 학습/테스트 분할 결과입니다."
)

report_files = list(REPORT_DIR.glob("*.csv")) if REPORT_DIR.exists() else []
if report_files:
    latest_report = max(report_files, key=lambda path: path.stat().st_mtime)
    latest_time = pd.Timestamp(latest_report.stat().st_mtime, unit="s").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    st.sidebar.success(f"최근 결과 생성: {latest_time}")
else:
    st.sidebar.warning("생성된 모델 평가 결과가 없습니다.")

st.sidebar.header("결과 갱신 방법")
st.sidebar.code(
    "\n".join(
        [
            "python src/classification.py",
            "python src/regression.py",
            "python src/clustering.py",
        ]
    ),
    language="bash",
)
if st.sidebar.button("화면 새로고침"):
    st.rerun()

classification_metrics = read_report("classification_metrics.csv")
regression_metrics = read_report("regression_metrics.csv")
clustering_metrics = read_report("clustering_metrics.csv")

# 이전 형식의 결과도 대시보드가 열리도록 Test 결과로 간주한다.
if classification_metrics is not None and "Dataset" not in classification_metrics:
    classification_metrics["Dataset"] = "Test"
    classification_metrics["Sample_Count"] = np.nan
if regression_metrics is not None and "Dataset" not in regression_metrics:
    regression_metrics["Dataset"] = "Test"
    regression_metrics["Sample_Count"] = np.nan

classification_test_metrics = (
    classification_metrics.loc[classification_metrics["Dataset"] == "Test"]
    if classification_metrics is not None
    else None
)
regression_test_metrics = (
    regression_metrics.loc[regression_metrics["Dataset"] == "Test"]
    if regression_metrics is not None
    else None
)

st.subheader("핵심 성능 요약")
summary_columns = st.columns(3)

with summary_columns[0]:
    if classification_test_metrics is not None:
        best = classification_test_metrics.loc[
            classification_test_metrics["F1"].idxmax()
        ]
        st.metric("최고 Test 분류 F1", f"{best['F1']:.3f}")
        st.caption(f"모델: {MODEL_LABELS.get(best['Model'], best['Model'])}")
    else:
        st.metric("최고 Test 분류 F1", "결과 없음")

with summary_columns[1]:
    if regression_test_metrics is not None:
        best = regression_test_metrics.loc[
            regression_test_metrics["RMSE"].idxmin()
        ]
        st.metric("최저 Test 회귀 RMSE", f"{best['RMSE']:.3f}")
        st.caption(f"모델: {MODEL_LABELS.get(best['Model'], best['Model'])}")
    else:
        st.metric("최저 Test 회귀 RMSE", "결과 없음")

with summary_columns[2]:
    if clustering_metrics is not None:
        clustering_result = clustering_metrics.iloc[0]
        st.metric(
            "군집 Silhouette",
            f"{clustering_result['Silhouette_Score']:.3f}",
        )
        st.caption(f"군집 수: k={int(clustering_result['N_Clusters'])}")
    else:
        st.metric("군집 Silhouette", "결과 없음")

classification_tab, regression_tab, clustering_tab = st.tabs(
    ["분류", "회귀", "군집"]
)

with classification_tab:
    st.header("누가 이탈할 것인가?")
    st.write("이탈 고객(`Target=1`) 예측 성능을 비교합니다.")

    if classification_metrics is None:
        show_missing_result(
            "classification_metrics.csv",
            "python src/classification.py",
        )
    else:
        shown_metrics = display_model_names(classification_metrics)
        st.dataframe(
            shown_metrics.style.format(
                {
                    "Sample_Count": "{:.0f}",
                    "Accuracy": "{:.3f}",
                    "Precision": "{:.3f}",
                    "Recall": "{:.3f}",
                    "F1": "{:.3f}",
                    "ROC_AUC": "{:.3f}",
                }
            ),
            hide_index=True,
            width="stretch",
        )

        selected_metric = st.selectbox(
            "비교할 분류 지표",
            ["F1", "Recall", "Precision", "ROC_AUC", "Accuracy"],
            format_func=lambda metric: CLASSIFICATION_METRIC_LABELS[metric],
        )
        st.altair_chart(
            make_classification_chart(shown_metrics, selected_metric),
            width="stretch",
        )
        st.caption("파란색은 Train, 주황색은 Test 성능입니다.")

        train_metrics = classification_metrics.loc[
            classification_metrics["Dataset"] == "Train"
        ].set_index("Model")
        test_metrics = classification_metrics.loc[
            classification_metrics["Dataset"] == "Test"
        ].set_index("Model")
        common_models = train_metrics.index.intersection(test_metrics.index)

        if len(common_models) > 0:
            overfit_data = pd.DataFrame(index=common_models)
            overfit_data["Train F1"] = train_metrics.loc[common_models, "F1"]
            overfit_data["Test F1"] = test_metrics.loc[common_models, "F1"]
            overfit_data["F1 차이"] = (
                overfit_data["Train F1"] - overfit_data["Test F1"]
            )
            overfit_data["Train ROC-AUC"] = train_metrics.loc[
                common_models, "ROC_AUC"
            ]
            overfit_data["Test ROC-AUC"] = test_metrics.loc[
                common_models, "ROC_AUC"
            ]
            overfit_data["ROC-AUC 차이"] = (
                overfit_data["Train ROC-AUC"] - overfit_data["Test ROC-AUC"]
            )
            overfit_data["상태"] = [
                classification_overfit_status(f1_gap, auc_gap)
                for f1_gap, auc_gap in zip(
                    overfit_data["F1 차이"],
                    overfit_data["ROC-AUC 차이"],
                )
            ]
            overfit_data.index = overfit_data.index.to_series().replace(
                MODEL_LABELS
            )
            overfit_data.index.name = "Model"

            st.subheader("Train/Test 과적합 점검")
            st.dataframe(
                overfit_data.reset_index().style.format(
                    {
                        "Train F1": "{:.3f}",
                        "Test F1": "{:.3f}",
                        "F1 차이": "{:.3f}",
                        "Train ROC-AUC": "{:.3f}",
                        "Test ROC-AUC": "{:.3f}",
                        "ROC-AUC 차이": "{:.3f}",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "차이 = Train - Test입니다. 양수 차이가 클수록 과적합 가능성이 "
                "높지만, 상태 기준은 빠른 점검을 위한 참고값입니다."
            )
        else:
            st.info(
                "Train/Test 비교는 분류 코드를 다시 실행하면 표시됩니다."
            )

        classification_predictions = read_report("classification_predictions.csv")
        if classification_predictions is None:
            st.info(
                "혼동행렬과 ROC 곡선은 분류 코드를 다시 실행하면 표시됩니다."
            )
        else:
            classification_model_options = display_model_names(
                classification_test_metrics
            )["Model"].tolist()
            best_classification_model = MODEL_LABELS.get(
                classification_test_metrics.loc[
                    classification_test_metrics["F1"].idxmax(), "Model"
                ],
                classification_test_metrics.loc[
                    classification_test_metrics["F1"].idxmax(), "Model"
                ],
            )
            selected_model_label = st.selectbox(
                "상세 분석 모델",
                classification_model_options,
                index=classification_model_options.index(
                    best_classification_model
                ),
                key="classification_model",
            )
            selected_model = next(
                (
                    key
                    for key, label in MODEL_LABELS.items()
                    if label == selected_model_label
                ),
                selected_model_label,
            )
            predictions = classification_predictions.loc[
                classification_predictions["Model"] == selected_model
            ]

            detail_columns = st.columns(2)
            with detail_columns[0]:
                st.subheader("혼동행렬")
                confusion_matrix = pd.crosstab(
                    predictions["Actual"],
                    predictions["Predicted"],
                ).reindex(index=[0, 1], columns=[0, 1], fill_value=0)
                confusion_matrix.index = ["실제 유지", "실제 이탈"]
                confusion_matrix.columns = ["예측 유지", "예측 이탈"]
                st.dataframe(confusion_matrix, width="stretch")

            with detail_columns[1]:
                st.subheader("ROC 곡선")
                false_positive_rate, true_positive_rate, _ = roc_curve(
                    predictions["Actual"],
                    predictions["Churn_Probability"],
                )
                roc_data = pd.DataFrame(
                    {
                        "False Positive Rate": false_positive_rate,
                        "모델": true_positive_rate,
                        "무작위 기준": false_positive_rate,
                    }
                ).set_index("False Positive Rate")
                st.line_chart(roc_data)

with regression_tab:
    st.header("고객의 거래 활동성은 어느 정도인가?")
    st.write("최근 12개월 거래건수(`Total_Trans_Ct`) 예측 성능을 비교합니다.")

    if regression_metrics is None:
        show_missing_result(
            "regression_metrics.csv",
            "python src/regression.py",
        )
    else:
        shown_metrics = display_model_names(regression_metrics)
        st.dataframe(
            shown_metrics.style.format(
                {
                    "Sample_Count": "{:.0f}",
                    "MAE": "{:.3f}",
                    "RMSE": "{:.3f}",
                    "R2": "{:.3f}",
                }
            ),
            hide_index=True,
            width="stretch",
        )

        selected_metric = st.selectbox(
            "비교할 회귀 지표",
            ["RMSE", "MAE", "R2"],
            format_func=lambda metric: REGRESSION_METRIC_LABELS[metric],
        )
        st.altair_chart(
            make_regression_chart(shown_metrics, selected_metric),
            width="stretch",
        )
        st.caption("파란색은 Train, 주황색은 Test 성능입니다.")

        train_metrics = regression_metrics.loc[
            regression_metrics["Dataset"] == "Train"
        ].set_index("Model")
        test_metrics = regression_metrics.loc[
            regression_metrics["Dataset"] == "Test"
        ].set_index("Model")
        common_models = train_metrics.index.intersection(test_metrics.index)

        if len(common_models) > 0:
            overfit_data = pd.DataFrame(index=common_models)
            overfit_data["Train R²"] = train_metrics.loc[common_models, "R2"]
            overfit_data["Test R²"] = test_metrics.loc[common_models, "R2"]
            overfit_data["R² 차이"] = (
                overfit_data["Train R²"] - overfit_data["Test R²"]
            )
            overfit_data["Train RMSE"] = train_metrics.loc[
                common_models, "RMSE"
            ]
            overfit_data["Test RMSE"] = test_metrics.loc[common_models, "RMSE"]
            overfit_data["RMSE 증가율"] = (
                overfit_data["Test RMSE"] / overfit_data["Train RMSE"] - 1
            )
            overfit_data["상태"] = [
                regression_overfit_status(r2_gap, rmse_increase)
                for r2_gap, rmse_increase in zip(
                    overfit_data["R² 차이"],
                    overfit_data["RMSE 증가율"],
                )
            ]
            overfit_data.index = overfit_data.index.to_series().replace(
                MODEL_LABELS
            )
            overfit_data.index.name = "Model"

            st.subheader("Train/Test 과적합 점검")
            st.dataframe(
                overfit_data.reset_index().style.format(
                    {
                        "Train R²": "{:.3f}",
                        "Test R²": "{:.3f}",
                        "R² 차이": "{:.3f}",
                        "Train RMSE": "{:.3f}",
                        "Test RMSE": "{:.3f}",
                        "RMSE 증가율": "{:.1%}",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "R² 차이는 Train - Test, RMSE 증가율은 Test가 Train보다 "
                "얼마나 커졌는지 나타냅니다. 상태 기준은 참고값입니다."
            )
        else:
            st.info(
                "Train/Test 비교는 회귀 코드를 다시 실행하면 표시됩니다."
            )

        regression_predictions = read_report("regression_predictions.csv")
        if regression_predictions is None:
            st.info(
                "실제값·예측값과 잔차 분석은 회귀 코드를 다시 실행하면 표시됩니다."
            )
        else:
            regression_model_options = display_model_names(
                regression_test_metrics
            )["Model"].tolist()
            best_regression_model = MODEL_LABELS.get(
                regression_test_metrics.loc[
                    regression_test_metrics["RMSE"].idxmin(), "Model"
                ],
                regression_test_metrics.loc[
                    regression_test_metrics["RMSE"].idxmin(), "Model"
                ],
            )
            selected_model_label = st.selectbox(
                "상세 분석 모델",
                regression_model_options,
                index=regression_model_options.index(best_regression_model),
                key="regression_model",
            )
            selected_model = next(
                (
                    key
                    for key, label in MODEL_LABELS.items()
                    if label == selected_model_label
                ),
                selected_model_label,
            )
            predictions = regression_predictions.loc[
                regression_predictions["Model"] == selected_model
            ]

            detail_columns = st.columns(2)
            with detail_columns[0]:
                st.subheader("실제값과 예측값")
                st.scatter_chart(
                    predictions,
                    x="Actual",
                    y="Predicted",
                )

            with detail_columns[1]:
                st.subheader("잔차 분포")
                counts, bin_edges = np.histogram(predictions["Residual"], bins=20)
                residual_histogram = pd.DataFrame(
                    {
                        "잔차 구간": [
                            f"{start:.1f} ~ {end:.1f}"
                            for start, end in zip(bin_edges[:-1], bin_edges[1:])
                        ],
                        "고객 수": counts,
                    }
                ).set_index("잔차 구간")
                st.bar_chart(residual_histogram)

with clustering_tab:
    st.header("어떤 고객 유형이 존재하는가?")
    st.write("고객 행동 특성으로 만든 K-means 군집의 품질과 특징을 확인합니다.")

    cluster_profile = read_report("clustering_profile.csv")
    cluster_assignments = read_report("clustering_assignments.csv")

    if clustering_metrics is None or cluster_profile is None:
        show_missing_result(
            "clustering_metrics.csv / clustering_profile.csv",
            "python src/clustering.py",
        )
    else:
        metric_columns = st.columns(3)
        clustering_result = clustering_metrics.iloc[0]
        metric_columns[0].metric(
            "군집 수",
            int(clustering_result["N_Clusters"]),
        )
        metric_columns[1].metric(
            "Silhouette Score",
            f"{clustering_result['Silhouette_Score']:.3f}",
        )
        metric_columns[2].metric(
            "Inertia",
            f"{clustering_result['Inertia']:,.1f}",
        )

        st.subheader("군집별 평균 프로파일")
        st.dataframe(
            cluster_profile.style.format(precision=3),
            hide_index=True,
            width="stretch",
        )

        profile_columns = st.columns(2)
        with profile_columns[0]:
            st.subheader("군집별 고객 수")
            st.altair_chart(
                make_cluster_profile_chart(
                    cluster_profile,
                    value_column="Customer_Count",
                    y_title="고객 수",
                    color="#2563EB",
                ),
                width="stretch",
            )
        with profile_columns[1]:
            st.subheader("군집별 이탈률")
            st.altair_chart(
                make_cluster_profile_chart(
                    cluster_profile,
                    value_column="Churn_Rate",
                    y_title="이탈률",
                    color="#F97316",
                    percentage=True,
                ),
                width="stretch",
            )

        if cluster_assignments is not None:
            st.subheader("거래건수와 카드 이용률 분포")
            scatter_data = cluster_assignments.sample(
                n=min(3000, len(cluster_assignments)),
                random_state=42,
            ).copy()
            scatter_data["Cluster"] = scatter_data["Cluster"].astype(str)
            st.scatter_chart(
                scatter_data,
                x="Total_Trans_Ct",
                y="Avg_Utilization_Ratio",
                color="Cluster",
            )
