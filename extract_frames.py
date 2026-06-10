import os
import sys

import cv2


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python extract_frames.py <video_path> [out_dir] [count]")
        return 2

    video_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) >= 3 else os.path.dirname(os.path.abspath(video_path))
    count = int(sys.argv[3]) if len(sys.argv) >= 4 else 12
    count = max(2, min(60, count))
    os.makedirs(out_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"cannot open video: {video_path}")
        return 1

    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

    idxs = []
    if frames <= 0:
        idxs = [0]
    else:
        # Evenly spaced frames across the whole clip
        for k in range(count):
            t = k / (count - 1)
            idxs.append(int(round(t * (frames - 1))))
        # Add a few around the middle to capture steady view
        mid = frames // 2
        idxs += [max(0, mid - 60), max(0, mid - 30), mid, min(frames - 1, mid + 30), min(frames - 1, mid + 60)]
        # Add a few near the start/end
        idxs += [min(10, frames - 1), max(0, frames - 20)]
    idxs = sorted(set(i for i in idxs if 0 <= i < max(1, frames)))

    written = []
    base = os.path.splitext(os.path.basename(video_path))[0]
    for i, idx in enumerate(idxs):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        out_path = os.path.join(out_dir, f"{base}_frame_{i:03d}_f{idx}.png")
        cv2.imwrite(out_path, frame)
        written.append(out_path)

    cap.release()
    print("frames", frames, "fps", fps)
    print("written", written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

