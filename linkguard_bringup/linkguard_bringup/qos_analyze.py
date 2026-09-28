"""Command-line entry point for the QoS experiment report generator."""

import argparse
from pathlib import Path

from .experiment_analysis import generate_report


def main(args=None) -> None:
    parser = argparse.ArgumentParser(
        description='Generate CSV summary, SVG charts, and a Markdown report.',
    )
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    options = parser.parse_args(args)
    input_path = options.input.expanduser().resolve()
    output_dir = options.output_dir.expanduser().resolve()
    summaries = generate_report(input_path, output_dir)
    print(f'Generated {len(summaries)} grouped summaries in {output_dir}')


if __name__ == '__main__':
    main()
