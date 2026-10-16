import os
import sys
import traceback

os.environ["HF_HOME"] = r"D:\hf_cache"

try:
    import torch
    print("PyTorch Version:", torch.__version__)
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    print("Loading t5-small tokenizer...")
    tok = AutoTokenizer.from_pretrained("t5-small")
    print("Loading t5-small model...")
    model = AutoModelForSeq2SeqLM.from_pretrained("t5-small")
    print("[OK] Model loaded successfully!")
    inp = tok("parse: church in Berlin", return_tensors="pt")
    lbl = tok('{"area":"Berlin"}', return_tensors="pt")
    print("Testing forward pass...")
    out = model(**inp, labels=lbl["input_ids"])
    print("Forward pass successful! Loss:", out.loss.item())
    print("Testing backward pass...")
    out.loss.backward()
    print("[OK] Backward pass successful!")
except Exception as e:
    traceback.print_exc()
