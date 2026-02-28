import json
import os
import random
import time
import re
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path("..") / ".env")

from openai import OpenAI

# Default (can be overridden via CLI)
DEFAULT_TRAINING_PATH = "training.jsonl"

EXISTING_FT_MODEL = "ft:gpt-4.1-mini-2025-04-14:personal:invisipeak-v3:DDycM6jP"  # optional
BASE_MODEL = "gpt-4.1-mini-2025-04-14"

POLL_SECONDS = 30
JOB_METADATA = {
    "project": "discord-snark",
    "dataset": "invisipeak",
}

# Hyperparameters (defaults; can be overridden via CLI)
DEFAULT_N_EPOCHS: int | str = 2  # or "auto"
BATCH_SIZE: int | str = "auto"   # or int
LR_MULT: float | str = "auto"    # or float

# Seed (optional; random if None)
SEED = None
if SEED is None:
    SEED = random.randint(0, 2**31 - 1)
else:
    SEED = int(SEED)


def compute_suffix(existing_ft_model: str | None, dataset_name: str) -> str:
    if not existing_ft_model:
        return f"{dataset_name}-v1"

    parts = existing_ft_model.split(":")
    if len(parts) < 2:
        return f"{dataset_name}-v1"

    prior_suffix = parts[-2]
    match = re.match(r"^(.*?)-v(\d+)$", prior_suffix)
    if match:
        base, version = match.groups()
        return f"{base}-v{int(version) + 1}"

    return f"{prior_suffix}-v2"


USE_SUFFIX = compute_suffix(EXISTING_FT_MODEL, JOB_METADATA["dataset"])


def validate_jsonl(path: Path) -> int:
    if not path.exists():
        raise FileNotFoundError(f"Training file not found: {path.resolve()}")

    bad = 0
    total = 0
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                obj = json.loads(line)
                msgs = obj.get("messages")
                if not isinstance(msgs, list) or len(msgs) < 2:
                    raise ValueError("Missing/invalid 'messages' array")
            except Exception as e:
                bad += 1
                print(f"[INVALID] line {i}: {e}")
                if bad >= 10:
                    break

    if bad:
        raise ValueError(
            f"Validation failed: {bad} bad lines (checked {total}). Fix JSONL and retry."
        )

    print(f"✅ JSONL looks valid ({total} examples).")
    return total


def wait_for_job(client: OpenAI, job_id: str, poll_seconds: int = 15) -> dict:
    while True:
        job = client.fine_tuning.jobs.retrieve(job_id)
        status = job.status
        print(f"Job {job_id} status: {status}")

        if status in ("succeeded", "failed", "cancelled"):
            return job.model_dump() if hasattr(job, "model_dump") else dict(job)

        time.sleep(poll_seconds)


def _yes_no_prompt(prompt: str) -> bool:
    while True:
        resp = input(prompt).strip().lower()
        if resp in {"y", "yes"}:
            return True
        if resp in {"n", "no"}:
            return False
        print("Please type 'yes' or 'no' (or 'y'/'n').")


def _parse_epochs(raw: str) -> int | str:
    s = str(raw).strip().lower()
    if s == "auto":
        return "auto"
    try:
        n = int(s)
    except ValueError:
        raise SystemExit(f"Invalid --epochs value: {raw!r} (use an int or 'auto')")
    if n <= 0:
        raise SystemExit("Invalid --epochs value: must be > 0 (or 'auto')")
    return n


def print_config(
    training_path: Path,
    starting_model: str,
    n_epochs: int | str,
    dry_run: bool,
    num_examples: int | None = None,
) -> None:
    print("\n========== Fine-tune configuration ==========")
    print(f"DRY_RUN:              {dry_run}")
    print(f"TRAINING_PATH:        {training_path.resolve()}")
    print(f"TRAINING_EXISTS:      {training_path.exists()}")
    print(f"NUM_EXAMPLES:         {num_examples if num_examples is not None else 'Not validated yet'}")
    print(f"BASE_MODEL:           {BASE_MODEL}")
    print(f"EXISTING_FT_MODEL:    {EXISTING_FT_MODEL!r}")
    print(f"STARTING_MODEL:       {starting_model}")
    print(f"USE_SUFFIX:           {USE_SUFFIX}")
    print(f"N_EPOCHS:             {n_epochs}")
    print(f"BATCH_SIZE:           {BATCH_SIZE}")
    print(f"LR_MULT:              {LR_MULT}")
    print(f"SEED:                 {SEED}")
    print(f"POLL_SECONDS:         {POLL_SECONDS}")
    print(f"JOB_METADATA:         {JOB_METADATA}")
    print("============================================\n")


def main():
    parser = argparse.ArgumentParser(description="OpenAI Fine-Tune Runner")
    parser.add_argument(
        "training_path",
        nargs="?",
        default=DEFAULT_TRAINING_PATH,
        help="Path to training JSONL file (default: training.jsonl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate + print configuration only. Do not upload files or create jobs.",
    )
    parser.add_argument(
        "--epochs",
        default=str(DEFAULT_N_EPOCHS),
        help="Override n_epochs hyperparameter (int or 'auto').",
    )
    args = parser.parse_args()

    training_path = Path(args.training_path)
    dry_run: bool = bool(args.dry_run)
    n_epochs: int | str = _parse_epochs(args.epochs)

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("openai_api_key")
    if not api_key and not dry_run:
        raise RuntimeError("Missing OPENAI_API_KEY (or openai_api_key) in env/.env")

    starting_model = EXISTING_FT_MODEL.strip() if EXISTING_FT_MODEL else BASE_MODEL

    num_examples = validate_jsonl(training_path)
    print_config(
        training_path,
        starting_model,
        n_epochs=n_epochs,
        dry_run=dry_run,
        num_examples=num_examples,
    )

    if dry_run:
        print("✅ Dry-run complete. No data uploaded; no job created.")
        return

    if not _yes_no_prompt("Proceed and send training data to OpenAI? (yes/no): "):
        print("Cancelled. Nothing was uploaded or created.")
        raise SystemExit(0)

    client = OpenAI(api_key=api_key)

    uploaded = client.files.create(
        file=training_path.open("rb"),
        purpose="fine-tune",
    )
    print(f"✅ Uploaded file: {uploaded.id}")

    job = client.fine_tuning.jobs.create(
        training_file=uploaded.id,
        model=starting_model,
        suffix=USE_SUFFIX,
        seed=SEED,
        method={
            "type": "supervised",
            "supervised": {
                "hyperparameters": {
                    "n_epochs": n_epochs,
                    "batch_size": BATCH_SIZE,
                    "learning_rate_multiplier": LR_MULT,
                },
            },
        },
        metadata={**JOB_METADATA, "starting_model": starting_model},
    )

    print(f"✅ Created fine-tune job: {job.id}")
    print(f"   Starting from: {starting_model}")

    final = wait_for_job(client, job.id, poll_seconds=POLL_SECONDS)

    if final.get("status") != "succeeded":
        print("❌ Fine-tune did not succeed.")
        print(final)
        raise SystemExit(1)

    ft_model = final.get("fine_tuned_model")
    print("\n🎉 Fine-tune succeeded!")
    print(f"Fine-tuned model: {ft_model}")
    print(f'\nsettings.openai_model = "{ft_model}"')


if __name__ == "__main__":
    main()
