# SPDX-FileCopyrightText: 2026 Аббасов Дамад Надирович (Damad Abbasov)
# SPDX-License-Identifier: LicenseRef-ParkingEye-Freeware-EULA
# Parking Eye (TKRP2) — бесплатно для личного и учебного использования.
# Изменение и коммерческое использование без согласия автора запрещены, см. LICENSE.

import json
import os
import random
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download


REPO_ID = "Voxel51/PKLot"


def get_snapshot_dir() -> Path:
  """
  Downloads a tiny file and returns the snapshot directory that contains it.
  This works even if the dataset wasn't fully downloaded via `datasets`.
  """
  meta_path = hf_hub_download(REPO_ID, "metadata.json", repo_type="dataset")
  return Path(meta_path).parent


def load_samples(snapshot_dir: Path) -> list[dict]:
  samples_path = snapshot_dir / "samples.json"
  with samples_path.open("r", encoding="utf-8") as f:
    data = json.load(f)
  samples = data.get("samples", [])
  if not isinstance(samples, list):
    raise ValueError("samples.json: 'samples' is not a list")
  return samples


def normalize_status(status: str) -> str:
  s = (status or "").strip().lower()
  # PKLot uses strings like "occupied" / "not occupied"
  if "not" in s and "occup" in s:
    return "free"
  if "occup" in s:
    return "occupied"
  return "unknown"


def polyline_to_yolo_seg_line(class_id: int, points: list[list[float]]) -> str | None:
  # points: [[x,y], ...] normalized 0..1, origin top-left (FiftyOne format)
  if not points or len(points) < 3:
    return None
  flat: list[str] = []
  for xy in points:
    if not isinstance(xy, list) or len(xy) != 2:
      continue
    x, y = float(xy[0]), float(xy[1])
    # clamp
    x = 0.0 if x < 0 else 1.0 if x > 1 else x
    y = 0.0 if y < 0 else 1.0 if y > 1 else y
    flat.append(f"{x:.6f}")
    flat.append(f"{y:.6f}")
  if len(flat) < 6:
    return None
  return f"{class_id} " + " ".join(flat)


def safe_name(sample: dict) -> str:
  # Unique-ish filename for output images
  src = str(sample.get("source", "src"))
  fp = str(sample.get("filepath", "image.jpg"))
  base = os.path.basename(fp)
  return f"{src}__{base}"


def ensure_image_local(snapshot_dir: Path, hf_path: str) -> Path:
  local = snapshot_dir / hf_path
  if local.exists():
    return local
  # If not present in snapshot dir, download this file into cache
  downloaded = hf_hub_download(REPO_ID, hf_path, repo_type="dataset")
  return Path(downloaded)


def main() -> None:
  out_root = Path(os.environ.get("PKLOT_YOLO_OUT", "pklot_yolo_seg")).resolve()
  seed = int(os.environ.get("PKLOT_SEED", "42"))
  val_ratio = float(os.environ.get("PKLOT_VAL_RATIO", "0.2"))

  print(f"Output: {out_root}")
  print(f"Seed: {seed}, val_ratio: {val_ratio}")

  snapshot_dir = get_snapshot_dir()
  print(f"Snapshot: {snapshot_dir}")

  samples = load_samples(snapshot_dir)
  print(f"Samples: {len(samples)}")

  rng = random.Random(seed)
  indices = list(range(len(samples)))
  rng.shuffle(indices)

  val_n = int(len(indices) * val_ratio)
  val_set = set(indices[:val_n])

  img_train = out_root / "images" / "train"
  img_val = out_root / "images" / "val"
  lab_train = out_root / "labels" / "train"
  lab_val = out_root / "labels" / "val"

  for d in [img_train, img_val, lab_train, lab_val]:
    d.mkdir(parents=True, exist_ok=True)

  # Classes: 0 = slot_free, 1 = slot_occupied
  unknown_status = 0
  written = 0

  for i, idx in enumerate(indices):
    s = samples[idx]
    split = "val" if idx in val_set else "train"

    hf_fp = str(s.get("filepath", "")).replace("\\", "/")
    if not hf_fp:
      continue

    name = safe_name(s)
    out_img = (img_val if split == "val" else img_train) / name
    out_lab = (lab_val if split == "val" else lab_train) / (Path(name).stem + ".txt")

    # Copy image
    src_img = ensure_image_local(snapshot_dir, hf_fp)
    if not out_img.exists():
      shutil.copy2(src_img, out_img)

    # Build labels from parking_spaces polylines
    ps = (s.get("parking_spaces") or {}).get("polylines", [])
    lines: list[str] = []
    if isinstance(ps, list):
      for p in ps:
        status = normalize_status(str(p.get("occupancy_status", "")))
        if status == "unknown":
          unknown_status += 1
          continue
        class_id = 0 if status == "free" else 1

        points_wrapped = p.get("points")
        # FiftyOne stores as [[[x,y], [x,y], ...]] (list of paths)
        if not isinstance(points_wrapped, list) or not points_wrapped:
          continue
        path0 = points_wrapped[0]
        if not isinstance(path0, list):
          continue

        line = polyline_to_yolo_seg_line(class_id, path0)
        if line:
          lines.append(line)

    out_lab.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    written += 1

    if (i + 1) % 500 == 0:
      print(f"Processed {i+1}/{len(indices)}")

  # Write data.yaml
  data_yaml = out_root / "data.yaml"
  data_yaml.write_text(
    "\n".join(
      [
        f"path: {out_root.as_posix()}",
        "train: images/train",
        "val: images/val",
        "names:",
        "  0: slot_free",
        "  1: slot_occupied",
        "",
      ]
    ),
    encoding="utf-8",
  )

  print(f"Done. Images+labels written: {written}")
  print(f"Unknown occupancy_status skipped: {unknown_status}")
  print(f"data.yaml: {data_yaml}")


if __name__ == "__main__":
  main()

