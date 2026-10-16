"""
TraceSpot Evaluation Pipeline (evaluate.py)
Compares (a) Rule-based baseline vs (b) Fine-tuned T5-small model
on held-out test sets and handwritten benchmark queries.
Reports:
- Exact-match accuracy
- Tag Accuracy (Precision, Recall, F1)
- Relation & Time-mode Accuracy
- Average Latency (ms)
Saves results to ml/metrics.json for frontend visualization.
"""

import os
import sys
import json
import time
import re
from typing import Dict, List, Any, Tuple

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if os.path.exists("D:\\"):
    os.environ["HF_HOME"] = r"D:\hf_cache"
    os.makedirs(r"D:\hf_cache", exist_ok=True)

import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from ml.schema import TraceSpotQuery, sanitize_and_validate_dict
from ml.rules import parse_query_rule_based

# Curated English Handwritten Benchmark Queries across spatial, time, and itinerary modes
HANDWRITTEN_BENCHMARK = [
    {
        "query": "pharmacy near a park in Berlin",
        "ground_truth": {
            "area": "Berlin",
            "entities": [{"id": 1, "name": "pharmacy", "tags": ["amenity=pharmacy"]}, {"id": 2, "name": "park", "tags": ["leisure=park"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 150}]
        }
    },
    {
        "query": "pharmacy within a 5 minute walk of a metro station in Berlin",
        "ground_truth": {
            "area": "Berlin",
            "entities": [{"id": 1, "name": "pharmacy", "tags": ["amenity=pharmacy"]}, {"id": 2, "name": "metro station", "tags": ["railway=subway_entrance"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "time_min": 5, "mode": "walk"}]
        }
    },
    {
        "query": "supermarket within 10 minutes walk of a train station in Chennai",
        "ground_truth": {
            "area": "Chennai",
            "entities": [{"id": 1, "name": "supermarket", "tags": ["shop=supermarket"]}, {"id": 2, "name": "train station", "tags": ["railway=station"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "time_min": 10, "mode": "walk"}]
        }
    },
    {
        "query": "cafe, then a park, then a restaurant, each within a 10 minute walk in Paris",
        "ground_truth": {
            "area": "Paris",
            "itinerary": {
                "stops": [
                    {"id": 1, "name": "cafe", "tags": ["amenity=cafe"]},
                    {"id": 2, "name": "park", "tags": ["leisure=park"]},
                    {"id": 3, "name": "restaurant", "tags": ["amenity=restaurant"]}
                ],
                "max_leg_min": 10
            }
        }
    },
    {
        "query": "bakery then a museum then a bar within 15 minutes walk in Hyderabad",
        "ground_truth": {
            "area": "Hyderabad",
            "itinerary": {
                "stops": [
                    {"id": 1, "name": "bakery", "tags": ["shop=bakery"]},
                    {"id": 2, "name": "museum", "tags": ["tourism=museum"]},
                    {"id": 3, "name": "bar", "tags": ["amenity=bar"]}
                ],
                "max_leg_min": 15
            }
        }
    },
    {
        "query": "church within 100 m of a river in Amsterdam",
        "ground_truth": {
            "area": "Amsterdam",
            "entities": [{"id": 1, "name": "church", "tags": ["amenity=place_of_worship"]}, {"id": 2, "name": "river", "tags": ["waterway=river"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 100}]
        }
    },
    {
        "query": "bench next to a fountain and a bus stop in Paris",
        "ground_truth": {
            "area": "Paris",
            "entities": [
                {"id": 1, "name": "bench", "tags": ["amenity=bench"]},
                {"id": 2, "name": "fountain", "tags": ["amenity=fountain"]},
                {"id": 3, "name": "bus stop", "tags": ["highway=bus_stop"]}
            ],
            "relations": [
                {"type": "within", "a": 1, "b": 2, "distance_m": 35},
                {"type": "within", "a": 1, "b": 3, "distance_m": 35}
            ]
        }
    },
    {
        "query": "hospital in London",
        "ground_truth": {
            "area": "London",
            "entities": [{"id": 1, "name": "hospital", "tags": ["amenity=hospital"]}],
            "relations": []
        }
    },
    {
        "query": "bakery near a school in Vienna",
        "ground_truth": {
            "area": "Vienna",
            "entities": [{"id": 1, "name": "bakery", "tags": ["shop=bakery"]}, {"id": 2, "name": "school", "tags": ["amenity=school"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 150}]
        }
    },
    {
        "query": "library next to a museum in Rome",
        "ground_truth": {
            "area": "Rome",
            "entities": [{"id": 1, "name": "library", "tags": ["amenity=library"]}, {"id": 2, "name": "museum", "tags": ["tourism=museum"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 35}]
        }
    },
    {
        "query": "restaurant within 50 m of a hotel in Munich",
        "ground_truth": {
            "area": "Munich",
            "entities": [{"id": 1, "name": "restaurant", "tags": ["amenity=restaurant"]}, {"id": 2, "name": "hotel", "tags": ["tourism=hotel"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 50}]
        }
    },
    {
        "query": "cafe within a 5 min walk of a library in Dublin",
        "ground_truth": {
            "area": "Dublin",
            "entities": [{"id": 1, "name": "cafe", "tags": ["amenity=cafe"]}, {"id": 2, "name": "library", "tags": ["amenity=library"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "time_min": 5, "mode": "walk"}]
        }
    },
    {
        "query": "supermarket near a parking lot in Brussels",
        "ground_truth": {
            "area": "Brussels",
            "entities": [{"id": 1, "name": "supermarket", "tags": ["shop=supermarket"]}, {"id": 2, "name": "parking", "tags": ["amenity=parking"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 150}]
        }
    },
    {
        "query": "bicycle parking next to a train station in Prague",
        "ground_truth": {
            "area": "Prague",
            "entities": [{"id": 1, "name": "bicycle parking", "tags": ["amenity=bicycle_parking"]}, {"id": 2, "name": "train station", "tags": ["railway=station"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 35}]
        }
    },
    {
        "query": "cafe within walking distance of a museum in Zurich",
        "ground_truth": {
            "area": "Zurich",
            "entities": [{"id": 1, "name": "cafe", "tags": ["amenity=cafe"]}, {"id": 2, "name": "museum", "tags": ["tourism=museum"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "time_min": 10, "mode": "walk"}]
        }
    }
]


class TraceSpotInferenceEngine:
    def __init__(self, checkpoint_dir: str = "ml/model_checkpoint"):
        self.checkpoint_dir = checkpoint_dir
        self.model = None
        self.tokenizer = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.load_model()

    def load_model(self):
        if os.path.exists(self.checkpoint_dir) and (
            os.path.exists(os.path.join(self.checkpoint_dir, "model.safetensors")) or
            os.path.exists(os.path.join(self.checkpoint_dir, "pytorch_model.bin"))
        ):
            try:
                print(f"[*] Loading fine-tuned model from {self.checkpoint_dir} on {self.device}...")
                self.tokenizer = AutoTokenizer.from_pretrained(self.checkpoint_dir)
                self.model = AutoModelForSeq2SeqLM.from_pretrained(self.checkpoint_dir)
                self.model.to(self.device)
                self.model.eval()
                print("[OK] Fine-tuned T5-small model loaded successfully.")
            except Exception as e:
                print(f"[!] Warning: Failed loading checkpoint ({e}). Will use rule-based fallback.")
                self.model = None
        else:
            print(f"[*] No checkpoint found at '{self.checkpoint_dir}'. (Run ml/train.py to train).")

    def parse_with_model(self, query_text: str) -> Tuple[TraceSpotQuery, float, str]:
        """
        Parses query with fine-tuned model + safety layer validation.
        Returns (parsed_query, latency_ms, method_used).
        """
        start = time.perf_counter()
        if self.model is None or self.tokenizer is None:
            res = parse_query_rule_based(query_text)
            latency = (time.perf_counter() - start) * 1000
            return res, latency, "rule_based_fallback"

        prompt = "parse place query: " + query_text.strip()
        inputs = self.tokenizer(prompt, return_tensors="pt", max_length=80, truncation=True).to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_length=240,
                num_beams=2,
                early_stopping=True
            )

        decoded = self.tokenizer.decode(outputs[0], skip_special_tokens=True).strip()

        # Safety layer: validate JSON and tags
        try:
            json_match = re.search(r'\{.*\}', decoded)
            if json_match:
                raw_dict = json.loads(json_match.group(0))
            else:
                raw_dict = json.loads(decoded)
            validated = sanitize_and_validate_dict(raw_dict)
            latency = (time.perf_counter() - start) * 1000
            return validated, latency, "t5_fine_tuned"
        except Exception:
            # Fallback to rule parser
            validated = parse_query_rule_based(query_text)
            latency = (time.perf_counter() - start) * 1000
            return validated, latency, "safety_rule_fallback"

    def parse_with_baseline(self, query_text: str) -> Tuple[TraceSpotQuery, float]:
        """Runs the rule-based baseline."""
        start = time.perf_counter()
        res = parse_query_rule_based(query_text)
        latency = (time.perf_counter() - start) * 1000
        return res, latency


def calculate_metrics(predictions: List[TraceSpotQuery], ground_truths: List[Dict[str, Any]], latencies: List[float]) -> Dict[str, Any]:
    exact_matches = 0
    total_tags_p = 0
    total_tags_r = 0
    correct_tags = 0

    total_rels_p = 0
    total_rels_r = 0
    correct_rels = 0

    for pred, gt_dict in zip(predictions, ground_truths):
        gt = sanitize_and_validate_dict(gt_dict)
        pred_dict = pred.model_dump()
        gt_dump = gt.model_dump()

        # Check Area
        area_match = pred_dict["area"].lower() == gt_dump["area"].lower()

        # Check Tags
        pred_tags = set(tag for e in pred_dict.get("entities", []) for tag in e.get("tags", []))
        gt_tags = set(tag for e in gt_dump.get("entities", []) for tag in e.get("tags", []))

        total_tags_p += len(pred_tags)
        total_tags_r += len(gt_tags)
        correct_tags += len(pred_tags.intersection(gt_tags))

        # Check Relations (including time_min and mode)
        pred_rels = {(r["type"], r["a"], r["b"], r.get("distance_m"), r.get("time_min"), r.get("mode")) for r in pred_dict.get("relations", [])}
        gt_rels = {(r["type"], r["a"], r["b"], r.get("distance_m"), r.get("time_min"), r.get("mode")) for r in gt_dump.get("relations", [])}

        total_rels_p += len(pred_rels)
        total_rels_r += len(gt_rels)
        correct_rels += len(pred_rels.intersection(gt_rels))

        # Check Itinerary match
        itinerary_match = True
        if gt_dump.get("itinerary") or pred_dict.get("itinerary"):
            gt_itin = gt_dump.get("itinerary")
            pred_itin = pred_dict.get("itinerary")
            if not gt_itin or not pred_itin:
                itinerary_match = False
            else:
                gt_stops = [s["name"] for s in gt_itin.get("stops", [])]
                pred_stops = [s["name"] for s in pred_itin.get("stops", [])]
                itinerary_match = (gt_stops == pred_stops) and (gt_itin.get("max_leg_min") == pred_itin.get("max_leg_min"))

        # Check Exact Match
        if area_match and pred_tags == gt_tags and pred_rels == gt_rels and itinerary_match:
            exact_matches += 1

    n = len(predictions)
    tag_p = correct_tags / total_tags_p if total_tags_p > 0 else 1.0
    tag_r = correct_tags / total_tags_r if total_tags_r > 0 else 1.0
    tag_f1 = (2 * tag_p * tag_r) / (tag_p + tag_r) if (tag_p + tag_r) > 0 else 0.0

    rel_acc = correct_rels / total_rels_r if total_rels_r > 0 else 1.0
    exact_acc = exact_matches / n if n > 0 else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    return {
        "count": n,
        "exact_match_pct": round(exact_acc * 100, 2),
        "tag_precision_pct": round(tag_p * 100, 2),
        "tag_recall_pct": round(tag_r * 100, 2),
        "tag_f1_pct": round(tag_f1 * 100, 2),
        "relation_accuracy_pct": round(rel_acc * 100, 2),
        "avg_latency_ms": round(avg_latency, 2)
    }


def run_evaluation(test_file: str = "data/test.jsonl", max_test_samples: int = 50, output_path: str = "ml/metrics.json"):
    print("=" * 60)
    print("TraceSpot Comparative Evaluation Pipeline")
    print("=" * 60)

    engine = TraceSpotInferenceEngine()

    test_samples = []
    if os.path.exists(test_file):
        with open(test_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    test_samples.append({
                        "query": item["input_text"],
                        "ground_truth": item["target_json"]
                    })
                if len(test_samples) >= max_test_samples:
                    break

    eval_suite = {
        "handwritten": HANDWRITTEN_BENCHMARK,
        "held_out_test": test_samples
    }

    full_results = {}

    for suite_name, dataset in eval_suite.items():
        if not dataset:
            continue
        print(f"\n[*] Evaluating on '{suite_name}' ({len(dataset)} queries)...")

        # Baseline evaluation
        b_preds, b_lats = [], []
        for item in dataset:
            p, lat = engine.parse_with_baseline(item["query"])
            b_preds.append(p)
            b_lats.append(lat)

        gt_list = [item["ground_truth"] for item in dataset]
        b_metrics = calculate_metrics(b_preds, gt_list, b_lats)
        print(f"  [Baseline] Exact: {b_metrics['exact_match_pct']}% | Tag F1: {b_metrics['tag_f1_pct']}% | Rel Acc: {b_metrics['relation_accuracy_pct']}% | Lat: {b_metrics['avg_latency_ms']}ms")

        # Model evaluation
        m_preds, m_lats = [], []
        for item in dataset:
            p, lat, _ = engine.parse_with_model(item["query"])
            m_preds.append(p)
            m_lats.append(lat)

        m_metrics = calculate_metrics(m_preds, gt_list, m_lats)
        print(f"  [Model]    Exact: {m_metrics['exact_match_pct']}% | Tag F1: {m_metrics['tag_f1_pct']}% | Rel Acc: {m_metrics['relation_accuracy_pct']}% | Lat: {m_metrics['avg_latency_ms']}ms")

        full_results[suite_name] = {
            "baseline": b_metrics,
            "model": m_metrics
        }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2)

    print(f"\n[OK] Metrics saved successfully to '{output_path}'.")
    return full_results


if __name__ == "__main__":
    run_evaluation()
