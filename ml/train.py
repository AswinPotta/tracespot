"""
TraceSpot Model Training (train.py)
Fine-tunes t5-small to translate natural language place search queries into structured JSON.
Designed to run efficiently on CPU (< 30 minutes) or GPU if available.
Saves model checkpoint and tokenizer to ml/model_checkpoint/.
"""

import os
import sys
import json
import time
import argparse
from typing import List, Dict

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# If D:\ drive exists, use it for HF cache to avoid filling small C:\ drive
if os.path.exists("D:\\"):
    os.environ["HF_HOME"] = r"D:\hf_cache"
    os.makedirs(r"D:\hf_cache", exist_ok=True)

import torch

from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, get_linear_schedule_with_warmup


class QueryJSONDataset(Dataset):
    def __init__(self, data_path: str, tokenizer, max_input_len: int = 80, max_target_len: int = 240, max_samples: int = None):
        self.tokenizer = tokenizer
        self.max_input_len = max_input_len
        self.max_target_len = max_target_len
        self.examples = []

        if not os.path.exists(data_path):
            raise FileNotFoundError(f"Dataset file not found at {data_path}. Run ml/data_gen.py first.")

        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.examples.append(json.loads(line))
                if max_samples and len(self.examples) >= max_samples:
                    break

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        item = self.examples[idx]
        input_text = "parse place query: " + item["input_text"]
        target_text = item["target_text"]

        inputs = self.tokenizer(
            input_text,
            max_length=self.max_input_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt"
        )
        targets = self.tokenizer(
            target_text,
            max_length=self.max_target_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt"
        )

        labels = targets["input_ids"].squeeze(0)
        # Replace padding token id with -100 so CrossEntropy ignores them
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": inputs["input_ids"].squeeze(0),
            "attention_mask": inputs["attention_mask"].squeeze(0),
            "labels": labels
        }


def train_model(
    train_path: str = "data/train.jsonl",
    output_dir: str = "ml/model_checkpoint",
    epochs: int = 2,
    batch_size: int = 2,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 5e-4,
    max_samples: int = 500,
    force_cpu: bool = False
):
    import gc
    print("=" * 60)
    print("TraceSpot T5-Small Fine-Tuning Pipeline (Low-Memory CPU/GPU)")
    print("=" * 60)

    device = torch.device("cuda" if torch.cuda.is_available() and not force_cpu else "cpu")
    print(f"[*] Compute Device: {device}")
    if device.type == "cuda":
        print(f"[*] GPU Name: {torch.cuda.get_device_name(0)}")

    model_name = "t5-small"
    print(f"[*] Loading pretrained tokenizer and model: {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
    model.to(device)

    print(f"[*] Preparing training dataset (up to {max_samples} samples for rapid CPU execution)...")
    dataset = QueryJSONDataset(train_path, tokenizer, max_samples=max_samples)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    effective_batch = batch_size * gradient_accumulation_steps
    print(f"[*] Training samples: {len(dataset)}, Micro-batch: {batch_size}, Effective batch: {effective_batch}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
    total_steps = (len(dataloader) // gradient_accumulation_steps + 1) * epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=int(total_steps * 0.1), num_training_steps=total_steps)

    print(f"[*] Starting training for {epochs} epoch(s)...")
    start_time = time.time()
    model.train()
    optimizer.zero_grad()

    for epoch in range(1, epochs + 1):
        epoch_loss = 0.0
        step_count = 0
        epoch_start = time.time()

        for step, batch in enumerate(dataloader):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss / gradient_accumulation_steps
            loss.backward()

            epoch_loss += loss.item() * gradient_accumulation_steps
            step_count += 1

            if (step + 1) % gradient_accumulation_steps == 0 or (step + 1) == len(dataloader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

            if (step + 1) % 50 == 0 or (step + 1) == len(dataloader):
                avg_loss = epoch_loss / step_count
                elapsed = time.time() - epoch_start
                print(f"  Epoch [{epoch}/{epochs}] | Step [{step+1}/{len(dataloader)}] | Avg Loss: {avg_loss:.4f} | Time: {elapsed:.1f}s")

        gc.collect()

    total_duration = time.time() - start_time
    print(f"[OK] Training complete in {total_duration:.1f} seconds ({total_duration/60:.2f} mins).")

    print(f"[*] Saving model and tokenizer checkpoint to '{output_dir}'...")
    os.makedirs(output_dir, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    meta = {
        "model_name": model_name,
        "epochs": epochs,
        "batch_size": batch_size,
        "gradient_accumulation_steps": gradient_accumulation_steps,
        "learning_rate": learning_rate,
        "samples_trained": len(dataset),
        "device": str(device),
        "duration_sec": round(total_duration, 2),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(os.path.join(output_dir, "training_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"[OK] Checkpoint saved successfully to {output_dir}")



def parse_args():
    parser = argparse.ArgumentParser(description="TraceSpot T5-Small Training")
    parser.add_argument("--epochs", type=int, default=2, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=2, help="Micro-batch size for low RAM")
    parser.add_argument("--accum_steps", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=5e-4, help="Learning rate")
    parser.add_argument("--max_samples", type=int, default=300, help="Max samples from train set")
    parser.add_argument("--cpu", action="store_true", help="Force CPU training even if GPU exists")
    parser.add_argument("--data", type=str, default="data/train.jsonl", help="Path to train.jsonl")
    parser.add_argument("--output", type=str, default="ml/model_checkpoint", help="Output directory")
    return parser.parse_args()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    try:
        train_model(
            train_path=args.data,
            output_dir=args.output,
            epochs=args.epochs,
            batch_size=args.batch_size,
            gradient_accumulation_steps=args.accum_steps,
            learning_rate=args.lr,
            max_samples=args.max_samples,
            force_cpu=args.cpu
        )
    except Exception as e:
        import traceback
        traceback.print_exc()

