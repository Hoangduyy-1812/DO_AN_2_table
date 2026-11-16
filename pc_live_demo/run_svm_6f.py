"""Start the PC dashboard with the bundled six-feature SVM and data3 posture."""
import argparse
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--esp32-url', help='ESP32 URL for height sync, e.g. http://radar.local')
    parser.add_argument('--height', type=float, default=1.70, help='Mount height in metres; overridden by ESP32 sync when enabled')
    parser.add_argument('--tcp-port', type=int, default=9000)
    parser.add_argument('--web-port', type=int, default=8080)
    parser.add_argument('--out', type=Path, default=Path('data_web_session'))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1.0 <= args.height <= 2.5:
        parser.error('--height must be between 1.00 and 2.50 metres')

    root = Path(__file__).resolve().parent
    model_path = root / 'models' / 'fall_svm_6f_2s.joblib'
    try:
        import joblib
        from fall_window import feature_set_from_bundle
        bundle = joblib.load(model_path)
        if feature_set_from_bundle(bundle) != '6' or bundle.get('classifier') != 'svm':
            raise ValueError('Expected the bundled six-feature SVM model')
        import web_dashboard
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'Cannot start SVM: {exc}\nInstall dependencies with: py -3.12 -m pip install -r requirements.txt\n')

    print(f'MODEL: SVM RBF | FEATURES: 6 | WINDOW: 2 s | THRESHOLD: {bundle["threshold"]}', flush=True)
    print('POSTURE: data3 | LOW: 0.3555 m | HIGH: 0.9155 m | FALL HOLD: 8 s', flush=True)
    print('Height sync: ' + (args.esp32_url or f'manual {args.height:.2f} m'), flush=True)
    sys.argv = [str(root / 'web_dashboard.py'),
                '--model', str(model_path), '--posture-mode', 'data3',
                '--posture-config', str(root / 'posture_config_1p7m.json'),
                '--fsm-config', str(root / 'fsm_parameters_1p7m.json'),
                '--height', str(args.height), '--no-mqtt',
                '--tcp-port', str(args.tcp_port), '--web-port', str(args.web_port),
                '--out', str(args.out)]
    if args.esp32_url:
        sys.argv.extend(['--esp32-url', args.esp32_url])
    if args.no_browser:
        sys.argv.append('--no-browser')
    web_dashboard.main()


if __name__ == '__main__':
    main()
