"""Six original report features, plus the unchanged nine-feature reference.

The six-feature vector uses signed raw radar velocity (m/s), raw X/Y (mm
converted to m), and actual timestamps. The median-filtered Z is still used
by the unchanged FSM and by the nine-feature reference only.
"""

WINDOW_US = 2_000_000
STEP_US = 175_000
EDGE_TOLERANCE_US = 180_000
FEATURES_6 = (
    "peak_radial_speed_mps", "max_radial_accel_mps2", "delta_x_m",
    "delta_y_m", "radial_velocity_variance", "quiet_time_s",
)
FEATURES_9 = (
    "end_height_m", "height_drop_m", "height_range_m", "end_minus_start_m",
    "peak_radial_speed_mps", "mean_radial_speed_mps", "radial_speed_variance",
    "depth_range_m", "low_fraction",
)
FEATURE_SETS = {"6": FEATURES_6, "9": FEATURES_9}
FEATURES = FEATURES_6
QUIET_SPEED_MPS = 0.15


def feature_set_from_bundle(bundle):
    """Reject incompatible inputs instead of silently scoring the wrong vector."""
    names = tuple(bundle.get("features", ()))
    schema = next((key for key, value in FEATURE_SETS.items() if names == value), None)
    if schema is None or bundle.get("window_us") != WINDOW_US:
        raise ValueError("Model feature names/order or window length do not match this program.")
    if str(bundle.get("feature_set", schema)) != schema:
        raise ValueError("Model feature_set disagrees with its feature names.")
    if schema == "6" and bundle.get("feature_definition") != "report6_signed_raw_v1":
        raise ValueError("Six-feature model must use the report6_signed_raw_v1 definition.")
    model = bundle["model"]
    if getattr(model, "n_features_in_", None) != len(names):
        raise ValueError("Model input dimension does not match its feature metadata.")
    if list(model.classes_) != [0, 1]:
        raise ValueError("Model must have non-fall/fall classes [0, 1].")
    return schema


def extract_features(points, t_us, feature_set="6"):
    """Use the available samples in [t_us - 2 s, t_us], from one track."""
    if feature_set not in FEATURE_SETS:
        raise ValueError("feature_set must be '6' or '9'")
    if not points:
        return None
    cutoff = t_us - WINDOW_US
    if points[0]["t_us"] > cutoff + EDGE_TOLERANCE_US:
        return None

    window = []
    for point in reversed(points):
        if point["t_us"] > t_us:
            continue
        if point["t_us"] < cutoff:
            break
        window.append(point)
    if len(window) < 3:
        return None
    if feature_set == "6":
        chronological = list(reversed(window))
        velocities = [point["v_signed"] for point in chronological]
        xs = [point["x_mm"] / 1000.0 for point in chronological]
        ys = [point["y_mm"] / 1000.0 for point in chronological]
        intervals = [(right["t_us"] - left["t_us"]) / 1_000_000.0
                     for left, right in zip(chronological, chronological[1:])]
        if any(dt <= 0 or dt > 0.35 for dt in intervals):
            return None
        mean_v = sum(velocities) / len(velocities)
        return (
            max(abs(v) for v in velocities),
            max(abs(v1 - v0) / dt
                for v0, v1, dt in zip(velocities, velocities[1:], intervals)),
            sum(xs[-3:]) / 3.0 - sum(xs[:3]) / 3.0,
            sum(ys[-3:]) / 3.0 - sum(ys[:3]) / 3.0,
            sum((v - mean_v) ** 2 for v in velocities) / len(velocities),
            sum(dt for v, dt in zip(velocities[1:], intervals)
                if abs(v) < QUIET_SPEED_MPS),
        )
    heights = [point["zs"] for point in window]
    speeds = [point["v"] for point in window]
    depths = [point["y_mm"] for point in window]
    start = sum(heights[-3:]) / len(heights[-3:])
    end = sum(heights[:3]) / len(heights[:3])
    mean_speed = sum(speeds) / len(speeds)
    return (
        end, max(heights) - end, max(heights) - min(heights), end - start,
        max(speeds), mean_speed, sum((v - mean_speed) ** 2 for v in speeds) / len(speeds),
        (max(depths) - min(depths)) / 1000.0,
        sum(height < 0.48 for height in heights) / len(heights),
    )
