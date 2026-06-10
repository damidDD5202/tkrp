import argparse
import os
from pathlib import Path

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract frames from a video at a fixed rate."
    )
    parser.add_argument(
        "--video",
        required=True,
        help="Path to the input video file.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output directory for extracted frames.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=1.0,
        help="How many frames per second to save. Default: 1.0",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    video_path = Path(args.video)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")

    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if not source_fps or source_fps <= 0:
        source_fps = 30.0

    save_every_n = max(1, round(source_fps / max(args.fps, 0.001)))

    frame_idx = 0
    saved_idx = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_idx % save_every_n == 0:
            out_path = out_dir / f"frame_{saved_idx:06d}.jpg"
            cv2.imwrite(str(out_path), frame)
            saved_idx += 1

        frame_idx += 1

    cap.release()

    print(f"Saved {saved_idx} frames to {os.fspath(out_dir)}")


if __name__ == "__main__":
    main()
