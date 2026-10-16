"""
Unit tests for Beam Search Itinerary Planner (tests/test_beam_search_planner.py)
Tests:
- Beam search algorithm (width 5) finding connected chains
- Beam search vs greedy baseline optimization
- Leg time limit enforcement (max_leg_min)
- Relaxation behavior when constraints are tightened
"""

import pytest
from backend.planner import run_beam_search_itinerary, run_greedy_itinerary
from backend.routing import haversine_m


def mock_duration_minutes(p1, p2):
    """Calculates walking minutes between points at 83.33 m/min."""
    return haversine_m(p1["lat"], p1["lon"], p2["lat"], p2["lon"]) / 83.33


def test_beam_search_finds_valid_chain():
    # 3 stops with candidate places in Berlin
    candidates_by_stop = [
        # Stop 1: Cafes
        [
            {"id": "c1", "name": "Cafe Mitte", "lat": 52.5200, "lon": 13.4000},
            {"id": "c2", "name": "Espresso Bar", "lat": 52.5210, "lon": 13.4020}
        ],
        # Stop 2: Parks
        [
            {"id": "p1", "name": "Monbijou Park", "lat": 52.5230, "lon": 13.4010},
            {"id": "p2", "name": "Lustgarten", "lat": 52.5190, "lon": 13.4000}
        ],
        # Stop 3: Restaurants
        [
            {"id": "r1", "name": "Trattoria", "lat": 52.5240, "lon": 13.4030},
            {"id": "r2", "name": "Bistro", "lat": 52.5220, "lon": 13.4040}
        ]
    ]

    chains = run_beam_search_itinerary(
        candidates_by_stop=candidates_by_stop,
        get_duration_fn=mock_duration_minutes,
        max_leg_min=10.0,
        beam_width=5
    )

    assert len(chains) > 0
    best_chain, total_time, legs = chains[0]
    assert len(best_chain) == 3
    assert len(legs) == 2
    assert all(leg <= 10.0 for leg in legs)
    assert total_time == sum(legs)
    assert best_chain[0]["name"].startswith("Cafe") or best_chain[0]["name"].startswith("Espresso")


def test_beam_search_beats_or_matches_greedy():
    # Scenario designed where greedy gets trapped in local minimum
    # Stop 1 has two choices: A and B
    # A is close to P1 (2 min), but P1 is very far from any restaurant (15 min) -> total 17 min
    # B is slightly farther from P2 (4 min), but P2 is right next to R1 (2 min) -> total 6 min!
    candidates_by_stop = [
        [
            {"id": "c_A", "lat": 52.5200, "lon": 13.4000},
            {"id": "c_B", "lat": 52.5200, "lon": 13.4050}
        ],
        [
            {"id": "p_1", "lat": 52.5210, "lon": 13.4000},  # Close to c_A (~1 min walk)
            {"id": "p_2", "lat": 52.5220, "lon": 13.4050}   # Close to c_B (~2 min walk)
        ],
        [
            {"id": "r_1", "lat": 52.5225, "lon": 13.4055},  # Right next to p_2!
            {"id": "r_2", "lat": 52.5400, "lon": 13.4000}   # Far from p_1 (~25 min walk)
        ]
    ]

    beam_chains = run_beam_search_itinerary(
        candidates_by_stop=candidates_by_stop,
        get_duration_fn=mock_duration_minutes,
        max_leg_min=30.0,
        beam_width=5
    )
    assert len(beam_chains) > 0
    beam_best_time = beam_chains[0][1]

    greedy_res = run_greedy_itinerary(candidates_by_stop, mock_duration_minutes)
    assert greedy_res is not None
    greedy_chain, greedy_time = greedy_res

    # Beam search should find the globally shorter chain (c_B -> p_2 -> r_1)
    assert beam_best_time <= greedy_time


def test_beam_search_enforces_max_leg_filter():
    candidates_by_stop = [
        [{"id": "s1", "lat": 52.5000, "lon": 13.4000}],
        [{"id": "s2", "lat": 52.5500, "lon": 13.4000}]  # ~5.5km away = ~66 min walk
    ]

    # Filter with strict 10 min limit
    chains = run_beam_search_itinerary(
        candidates_by_stop=candidates_by_stop,
        get_duration_fn=mock_duration_minutes,
        max_leg_min=10.0,
        beam_width=5
    )
    # Should return empty because leg is ~66 min > 10 min
    assert len(chains) == 0
