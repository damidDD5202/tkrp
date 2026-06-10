from huggingface_hub import hf_hub_download


def main() -> None:
  for name in ["metadata.json", "samples.json"]:
    path = hf_hub_download(
      repo_id="Voxel51/PKLot",
      filename=name,
      repo_type="dataset",
    )
    print(f"{name}: {path}")


if __name__ == "__main__":
  main()

