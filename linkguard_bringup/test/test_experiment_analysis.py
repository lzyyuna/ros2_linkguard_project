import csv

from linkguard_bringup.experiment_analysis import generate_report, summarize_trials


def _row(reliability, profile, success, elapsed, delivery):
    return {
        'reliability': reliability,
        'profile': profile,
        'success': success,
        'elapsed_sec': elapsed,
        'delivery_rate_mean': delivery,
        'error': '',
        'latency_ms_mean': 20.0,
        'jitter_ms_mean': 5.0,
        'aoi_ms_max': 100.0,
        'transport_dropped_packets': 0.0,
        'application_dropped_packets': 0.0,
        'out_of_order_packets': 0.0,
        'degraded_duration_sec': 0.0,
        'stopped_duration_sec': 0.0,
    }


def test_disconnected_abort_is_an_expected_outcome():
    summaries = summarize_trials([
        _row('reliable', 'disconnected', False, 3.0, 0.0),
    ])
    assert summaries[0]['success_rate'] == 0.0
    assert summaries[0]['expected_outcome_rate'] == 1.0


def test_generate_report_creates_csv_svg_and_markdown(tmp_path):
    raw = tmp_path / 'trials.csv'
    fieldnames = [
        'reliability', 'profile', 'success', 'elapsed_sec',
        'delivery_rate_mean', 'error', 'latency_ms_mean', 'jitter_ms_mean',
        'aoi_ms_max', 'transport_dropped_packets',
        'application_dropped_packets', 'out_of_order_packets',
        'degraded_duration_sec', 'stopped_duration_sec',
    ]
    with raw.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(_row('reliable', 'good', True, 4.0, 1.0))
        writer.writerow(_row('best_effort', 'good', True, 4.2, 0.99))

    output = tmp_path / 'report'
    generate_report(raw, output)
    assert (output / 'qos_summary.csv').exists()
    assert (output / 'qos_elapsed.svg').exists()
    assert (output / 'QOS_EXPERIMENT_REPORT.md').exists()
