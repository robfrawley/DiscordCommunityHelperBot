import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path("..") / ".env")
from openai import OpenAI

TRAINING_PATH = Path("training.jsonl")
BASE_MODEL = "gpt-4.1-mini-2025-04-14"
N_EPOCHS = 2
POLL_SECONDS = 30

JOB_METADATA = {
    "project": "discord-snark",
    "dataset": "invisipeak",
}

def validate_jsonl(path: Path) -> None:
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
        raise ValueError(f"Validation failed: {bad} bad lines (checked {total}). Fix JSONL and retry.")
    print(f"✅ JSONL looks valid ({total} examples).")


def wait_for_job(client: OpenAI, job_id: str, poll_seconds: int = 15) -> dict:
    while True:
        job = client.fine_tuning.jobs.retrieve(job_id)
        status = job.status
        print(f"Job {job_id} status: {status}")

        if status in ("succeeded", "failed", "cancelled"):
            return job.model_dump() if hasattr(job, "model_dump") else dict(job)

        time.sleep(poll_seconds)


def main():
    client = OpenAI(
        api_key=os.getenv("openai_api_key"),
    )

    validate_jsonl(TRAINING_PATH)

    uploaded = client.files.create(
        file=TRAINING_PATH.open("rb"),
        purpose="fine-tune",
    )
    print(f"✅ Uploaded file: {uploaded.id}")

    job = client.fine_tuning.jobs.create(
        training_file=uploaded.id,
        model=BASE_MODEL,
        suffix="invisipeak-v1",
        method={
            "type": "supervised",
            "supervised": {
                "hyperparameters": {"n_epochs": N_EPOCHS},
            },
        },
        metadata=JOB_METADATA,
    )
    print(f"✅ Created fine-tune job: {job.id}")

    final = wait_for_job(client, job.id, poll_seconds=POLL_SECONDS)

    status = final.get("status")
    if status != "succeeded":
        print("❌ Fine-tune did not succeed.")
        print(final)
        raise SystemExit(1)

    ft_model = final.get("fine_tuned_model")
    print("\n🎉 Fine-tune succeeded!")
    print(f"Fine-tuned model: {ft_model}")
    print("\nPut this into your bot config, e.g.:")
    print(f'  settings.openai_model = "{ft_model}"')


if __name__ == "__main__":
    main()
