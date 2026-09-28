"""Pure-Python aggregation and SVG reporting for QoS experiments."""

import csv
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import statistics


NUMERIC_FIELDS = [
    'elapsed_sec', 'wall_time_sec', 'delivery_rate_mean',
    'delivery_rate_min', 'latency_ms_mean', 'jitter_ms_mean',
    'aoi_ms_mean', 'aoi_ms_max', 'sent_packets', 'delivered_packets',
    'application_dropped_packets', 'transport_dropped_packets',
    'out_of_order_packets', 'good_duration_sec', 'degraded_duration_sec',
    'stopped_duration_sec',
]


SUMMARY_FIELDS = [
    'reliability', 'profile', 'runs', 'valid_runs', 'error_runs',
    'success_rate', 'expected_outcome_rate', 'elapsed_mean_sec',
    'elapsed_std_sec', 'delivery_mean', 'delivery_std', 'latency_mean_ms',
    'jitter_mean_ms', 'aoi_max_mean_ms', 'transport_dropped_mean',
    'application_dropped_mean', 'out_of_order_mean',
    'degraded_duration_mean_sec', 'stopped_duration_mean_sec',
]


def _as_float(row, name):
    value = row.get(name, '')
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_bool(value):
    return str(value).strip().lower() in ('1', 'true', 'yes')


def _mean(values):
    return statistics.fmean(values) if values else 0.0


def _std(values):
    return statistics.stdev(values) if len(values) > 1 else 0.0


def load_trials(path: Path):
    with path.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row['success'] = _as_bool(row.get('success'))
        for field in NUMERIC_FIELDS:
            row[field] = _as_float(row, field)
    return rows


def summarize_trials(rows):
    groups = {}
    for row in rows:
        key = (row.get('reliability', ''), row.get('profile', ''))
        groups.setdefault(key, []).append(row)

    summaries = []
    for (reliability, profile), group in sorted(groups.items()):
        valid = [row for row in group if not row.get('error')]
        successes = [1.0 if row['success'] else 0.0 for row in valid]
        expected = [
            1.0
            if row['success'] == (profile != 'disconnected')
            else 0.0
            for row in valid
        ]
        elapsed = [row['elapsed_sec'] for row in valid]
        delivery = [row['delivery_rate_mean'] for row in valid]
        summary = {
            'reliability': reliability,
            'profile': profile,
            'runs': len(group),
            'valid_runs': len(valid),
            'error_runs': len(group) - len(valid),
            'success_rate': _mean(successes),
            'expected_outcome_rate': _mean(expected),
            'elapsed_mean_sec': _mean(elapsed),
            'elapsed_std_sec': _std(elapsed),
            'delivery_mean': _mean(delivery),
            'delivery_std': _std(delivery),
            'latency_mean_ms': _mean(
                [row['latency_ms_mean'] for row in valid]
            ),
            'jitter_mean_ms': _mean(
                [row['jitter_ms_mean'] for row in valid]
            ),
            'aoi_max_mean_ms': _mean([row['aoi_ms_max'] for row in valid]),
            'transport_dropped_mean': _mean(
                [row['transport_dropped_packets'] for row in valid]
            ),
            'application_dropped_mean': _mean(
                [row['application_dropped_packets'] for row in valid]
            ),
            'out_of_order_mean': _mean(
                [row['out_of_order_packets'] for row in valid]
            ),
            'degraded_duration_mean_sec': _mean(
                [row['degraded_duration_sec'] for row in valid]
            ),
            'stopped_duration_mean_sec': _mean(
                [row['stopped_duration_sec'] for row in valid]
            ),
        }
        summaries.append(summary)
    return summaries


def write_summary_csv(path: Path, summaries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(summary)


def write_grouped_bar_svg(
    path: Path,
    summaries,
    value_field: str,
    title: str,
    y_label: str,
    fixed_max=None,
) -> None:
    profiles = sorted({item['profile'] for item in summaries})
    reliabilities = sorted({item['reliability'] for item in summaries})
    lookup = {
        (item['profile'], item['reliability']): float(item[value_field])
        for item in summaries
    }
    values = list(lookup.values())
    maximum = fixed_max if fixed_max is not None else max(values, default=1.0)
    maximum = max(maximum, 1e-9)
    width, height = 900, 520
    left, right, top, bottom = 90, 30, 65, 90
    chart_width = width - left - right
    chart_height = height - top - bottom
    group_width = chart_width / max(1, len(profiles))
    bar_width = min(70, group_width / max(1, len(reliabilities) + 1))
    colors = ['#2563eb', '#f97316', '#16a34a', '#9333ea']

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="32" text-anchor="middle" '
        f'font-family="sans-serif" font-size="22">{escape(title)}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" '
        f'y2="{top + chart_height}" stroke="#334155"/>',
        f'<line x1="{left}" y1="{top + chart_height}" '
        f'x2="{left + chart_width}" y2="{top + chart_height}" '
        f'stroke="#334155"/>',
    ]
    for tick in range(6):
        value = maximum * tick / 5
        y = top + chart_height - chart_height * tick / 5
        parts.extend([
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_width}" '
            f'y2="{y:.1f}" stroke="#e2e8f0"/>',
            f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-family="sans-serif" font-size="12">{value:.2f}</text>',
        ])

    for group_index, profile in enumerate(profiles):
        center = left + group_width * (group_index + 0.5)
        offset = -bar_width * (len(reliabilities) - 1) / 2
        for series_index, reliability in enumerate(reliabilities):
            value = lookup.get((profile, reliability), 0.0)
            bar_height = chart_height * value / maximum
            x = center + offset + series_index * bar_width - bar_width * 0.4
            y = top + chart_height - bar_height
            parts.extend([
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width * 0.8:.1f}" '
                f'height="{bar_height:.1f}" fill="{colors[series_index % len(colors)]}"/>',
                f'<text x="{x + bar_width * 0.4:.1f}" y="{max(top + 12, y - 5):.1f}" '
                f'text-anchor="middle" font-family="sans-serif" font-size="11">'
                f'{value:.3f}</text>',
            ])
        parts.append(
            f'<text x="{center:.1f}" y="{top + chart_height + 24}" '
            f'text-anchor="middle" font-family="sans-serif" font-size="14">'
            f'{escape(profile)}</text>'
        )

    legend_x = left + 10
    for index, reliability in enumerate(reliabilities):
        x = legend_x + index * 180
        parts.extend([
            f'<rect x="{x}" y="{height - 35}" width="15" height="15" '
            f'fill="{colors[index % len(colors)]}"/>',
            f'<text x="{x + 22}" y="{height - 22}" '
            f'font-family="sans-serif" font-size="13">{escape(reliability)}</text>',
        ])
    parts.extend([
        f'<text transform="translate(20 {top + chart_height / 2}) rotate(-90)" '
        f'text-anchor="middle" font-family="sans-serif" font-size="14">'
        f'{escape(y_label)}</text>',
        '</svg>',
    ])
    path.write_text('\n'.join(parts), encoding='utf-8')


def _fmt(value, digits=3):
    return f'{float(value):.{digits}f}'


def write_report(path: Path, input_path: Path, rows, summaries) -> None:
    by_key = {
        (item['reliability'], item['profile']): item for item in summaries
    }
    lines = [
        '# LinkGuard QoS重复对照实验报告',
        '',
        f'- 生成时间：{datetime.now(timezone.utc).isoformat()}',
        f'- 原始数据：`{input_path.name}`',
        f'- 原始记录数：{len(rows)}',
        '- 对照变量：命令Topic reliability（RELIABLE / BEST_EFFORT）',
        '- 控制变量：相同目标、QoS depth、网络profile，以及配对随机种子',
        '',
        '## 汇总结果',
        '',
        '| QoS | 场景 | 有效/总次数 | 成功率 | 预期结果率 | 任务耗时均值±标准差(s) | 交付率均值±标准差 | 延迟(ms) | 抖动(ms) | DDS缺口均值 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for item in summaries:
        lines.append(
            f'| {item["reliability"]} | {item["profile"]} | '
            f'{item["valid_runs"]}/{item["runs"]} | '
            f'{_fmt(item["success_rate"])} | '
            f'{_fmt(item["expected_outcome_rate"])} | '
            f'{_fmt(item["elapsed_mean_sec"])} ± {_fmt(item["elapsed_std_sec"])} | '
            f'{_fmt(item["delivery_mean"])} ± {_fmt(item["delivery_std"])} | '
            f'{_fmt(item["latency_mean_ms"], 1)} | '
            f'{_fmt(item["jitter_mean_ms"], 1)} | '
            f'{_fmt(item["transport_dropped_mean"], 2)} |'
        )

    lines.extend([
        '',
        '## 图表',
        '',
        '![任务耗时](qos_elapsed.svg)',
        '',
        '![实测交付率](qos_delivery.svg)',
        '',
        '![DDS传输缺口](qos_transport_drops.svg)',
        '',
        '![预期结果率](qos_expected_outcome.svg)',
        '',
        '## 自动生成的观察',
        '',
    ])

    profiles = sorted({item['profile'] for item in summaries})
    for profile in profiles:
        reliable = by_key.get(('reliable', profile))
        best_effort = by_key.get(('best_effort', profile))
        if not reliable or not best_effort:
            lines.append(f'- `{profile}`：缺少一组QoS数据，不能完成对照。')
            continue
        delivery_difference = (
            reliable['delivery_mean'] - best_effort['delivery_mean']
        )
        elapsed_difference = (
            reliable['elapsed_mean_sec'] - best_effort['elapsed_mean_sec']
        )
        lines.append(
            f'- `{profile}`：RELIABLE相对BEST_EFFORT的平均交付率差值为'
            f'{delivery_difference:+.3f}，任务耗时差值为'
            f'{elapsed_difference:+.3f}s。'
        )

    error_count = sum(1 for row in rows if row.get('error'))
    lines.extend([
        '',
        '## 结论边界',
        '',
        f'- 本次记录中有 `{error_count}` 次实验基础设施错误；这些行未进入指标均值。',
        '- `disconnected`场景的预期结果是Action中止，因此成功率为0不代表测试失败；应查看“预期结果率”。',
        '- 应用层`drop_rate`发生在link_emulator内部，RELIABLE不会恢复模拟器主动丢弃的报文。',
        '- 单机环境中的DDS链路通常非常稳定；若两种QoS差异很小，这是合理结果，不应夸大结论。',
        '- 真正评价QoS抗拥塞能力，还需要受控带宽、CPU压力或跨主机网络实验。',
        '',
        '## 可复现命令',
        '',
        '```bash',
        'ros2 run linkguard_bringup qos_experiment --repetitions 10',
        'ros2 run linkguard_bringup qos_analyze \\',
        '  --input experiments/results/qos_trials.csv \\',
        '  --output-dir experiments/results/report',
        '```',
    ])
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def generate_report(input_path: Path, output_dir: Path):
    rows = load_trials(input_path)
    if not rows:
        raise ValueError('input CSV contains no experiment rows')
    summaries = summarize_trials(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_summary_csv(output_dir / 'qos_summary.csv', summaries)
    write_grouped_bar_svg(
        output_dir / 'qos_elapsed.svg', summaries,
        'elapsed_mean_sec', 'Mean mission duration', 'seconds',
    )
    write_grouped_bar_svg(
        output_dir / 'qos_delivery.svg', summaries,
        'delivery_mean', 'Mean measured delivery rate', 'ratio', fixed_max=1.0,
    )
    write_grouped_bar_svg(
        output_dir / 'qos_transport_drops.svg', summaries,
        'transport_dropped_mean', 'Mean inferred DDS transport gaps', 'packets',
    )
    write_grouped_bar_svg(
        output_dir / 'qos_expected_outcome.svg', summaries,
        'expected_outcome_rate', 'Expected mission outcome rate', 'ratio',
        fixed_max=1.0,
    )
    write_report(
        output_dir / 'QOS_EXPERIMENT_REPORT.md', input_path, rows, summaries
    )
    return summaries
