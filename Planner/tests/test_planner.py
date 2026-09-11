import json
import os
import time
from datetime import datetime

import pytest

import app as A


SAT = datetime(2026, 9, 12, 17, 0)   # Saturday, 2026-09-12
THU = datetime(2026, 9, 10, 18, 0)   # Thursday, 2026-09-10 (school day)
MON = datetime(2026, 9, 14, 17, 0)   # Monday, 2026-09-14 (school day)


@pytest.fixture
def tmp_data(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "DATA_FILE", str(tmp_path / "planner.json"))
    return A.DATA_FILE


@pytest.fixture
def client(tmp_data):
    A.app.config["TESTING"] = True
    with A.app.test_client() as c:
        yield c


# ---------------- build_plan ----------------

def test_build_plan_weekend_layout():
    plan, err = A.build_plan(
        [{"subject": "Math", "topic": "Algebra", "confidence": "red"},
         {"subject": "Physics", "topic": "Kinematics", "confidence": "green"}],
        "17:00", "19:00", 2, "practice", "A", now=SAT)
    assert err is None
    blocks = plan["blocks"]
    assert [b["type"] for b in blocks] == ["study", "break", "study"]
    assert blocks[0]["topic"] == "Algebra"            # red before green
    assert [b["duration"] for b in blocks] == [60, 10, 30]
    assert blocks[0]["time"] == "17:00-18:00"
    assert blocks[2]["time"] == "18:10-18:40"
    assert plan["stats"] == {"total_min": 90, "done_min": 0, "done_count": 0}
    assert plan["meta"]["fit"]["scaled"] is False


def test_build_plan_school_window_clamped():
    plan, err = A.build_plan(
        [{"subject": "Math", "topic": "Algebra", "confidence": "red"}],
        "12:00", "15:00", 3, "practice", "A", now=THU)
    assert err is None
    assert plan["meta"]["school"]["clamped_to_after_school"] is True
    assert plan["blocks"][0]["start"] == A.SCHOOL_END  # 15:30


def test_build_plan_urgency_order_school_day():
    # Thursday: today = TUR,BIO,MATH,HIS,ECL ; Friday = GER,PE,R&E,CHE,GEO,ENG
    plan, err = A.build_plan(
        [{"subject": "Math", "topic": "Algebra", "confidence": "red"},
         {"subject": "Biology", "topic": "Cell Biology", "confidence": "green"},
         {"subject": "Chemistry", "topic": "Bonding", "confidence": "green"},
         {"subject": "Physics", "topic": "Waves", "confidence": "red"}],
        "17:00", "21:00", 4, "practice", "A", now=THU)
    assert err is None
    order = [b["topic"] for b in plan["blocks"] if b["type"] == "study"]
    # today's subjects first (red within today), then tomorrow, then rest
    assert order == ["Algebra", "Cell Biology", "Bonding", "Waves"]


def test_build_plan_scales_when_window_too_small():
    topics = [{"subject": "Math", "topic": f"T{i}", "confidence": "red"} for i in range(5)]
    plan, err = A.build_plan(topics, "17:00", "19:00", 2, "practice", "A", now=SAT)
    assert err is None
    assert plan["meta"]["fit"]["scaled"] is True
    study = [b for b in plan["blocks"] if b["type"] == "study"]
    assert len(study) == 5
    assert all(b["duration"] >= 5 for b in study)
    total = sum(b["duration"] for b in study) + sum(b["duration"] for b in plan["blocks"] if b["type"] == "break")
    assert total <= 120  # fits the 2h window


def test_build_plan_rejects_bad_window():
    assert A.build_plan([{"subject": "M", "topic": "T", "confidence": "red"}],
                        "19:00", "17:00", 2, "practice", "A", now=SAT)[1]
    assert A.build_plan([{"subject": "M", "topic": "T", "confidence": "red"}],
                        "17:00", "17:10", 2, "practice", "A", now=SAT)[1]
    assert A.build_plan([], "17:00", "19:00", 2, "practice", "A", now=SAT)[1]


# ---------------- persistence / repair ----------------

def test_repair_keeps_extension_and_session(tmp_data):
    plan, _ = A.build_plan(
        [{"subject": "Math", "topic": "Algebra", "confidence": "red"}],
        "17:00", "19:00", 2, "practice", "A", now=SAT)
    blk = next(b for b in plan["blocks"] if b["type"] == "study")
    blk["duration"] += 15          # user extended
    blk["active"] = True           # session running
    blk["started_at"] = int(time.time()) - 120
    blk["elapsed"] = 30
    A._save_doc({"day": A._day_key(int(time.time())), "plan": plan})

    loaded = A._load_doc()
    b2 = next(b for b in loaded["plan"]["blocks"] if b["type"] == "study")
    assert b2["duration"] == blk["duration"]
    assert b2["active"] is True
    assert b2["started_at"] == blk["started_at"]
    assert b2["elapsed"] == 30


def test_repair_normalizes_legacy_block(tmp_data):
    legacy = {"id": "x", "start": 600, "end": 660, "time": "10:00-11:00",
              "type": "study", "subject": "M", "topic": "T", "confidence": "green",
              "status": "pending"}
    A._save_doc({"day": A._day_key(int(time.time())),
                 "plan": {"id": "p", "input": {"start": "10:00"}, "blocks": [legacy], "meta": {}}})
    b2 = A._load_doc()["plan"]["blocks"][0]
    assert b2["duration"] == 60
    assert b2["origDuration"] == 60
    assert b2["active"] is False


def test_save_is_atomic(tmp_data):
    A._save_doc({"a": 1})
    with open(tmp_data, encoding="utf-8") as fh:
        assert json.load(fh) == {"a": 1}
    assert not os.path.exists(tmp_data + ".tmp")


# ---------------- rollover ----------------

def _pending_block():
    return {"id": "b1", "start": 1020, "end": 1080, "time": "17:00-18:00",
            "duration": 60, "origDuration": 60, "type": "study",
            "subject": "Math", "topic": "Algebra", "confidence": "red",
            "status": "pending", "active": False, "elapsed": 0}


def test_rollover_moves_unfinished_to_missed(tmp_data):
    now = int(time.time())
    yesterday = A._day_key(now - 86400)
    two_days_ago = A._day_key(now - 2 * 86400)
    plan = {"id": "p", "created": "17:00",
            "input": {"topics": [_pending_block()], "start": "17:00", "end": "19:00",
                      "duration_h": 2, "mode": "practice", "criterion": "A"},
            "blocks": [_pending_block()], "meta": {}, "stats": {}}
    doc = {
        "day": yesterday,
        "plan": plan,
        "reviews": [
            {"id": "r1", "subject": "Math", "topic": "Algebra", "targetDay": two_days_ago,
             "label": "Hızlı Tekrar", "status": "pending", "added": two_days_ago},
            {"id": "r2", "subject": "Math", "topic": "Algebra", "targetDay": yesterday,
             "label": "Kendini Sınama", "status": "scheduled", "added": yesterday},
        ],
    }
    A._save_doc(doc)
    loaded = A._load_doc()
    assert loaded["plan"] is None
    assert loaded["day"] == A._day_key(now)
    missed = {(m["subject"], m["topic"]) for m in loaded["missed"]}
    assert ("Math", "Algebra") in missed                       # unfinished block
    assert any("Hızlı Tekrar" in m["topic"] for m in loaded["missed"])
    assert any("Kendini Sınama" in m["topic"] for m in loaded["missed"])  # scheduled->pending->missed


def test_no_rollover_same_day(tmp_data):
    now = int(time.time())
    plan = {"id": "p", "input": {"start": "17:00"}, "blocks": [_pending_block()], "meta": {}}
    A._save_doc({"day": A._day_key(now), "plan": plan})
    assert A._load_doc()["plan"] is not None


# ---------------- streak ----------------

def test_streak():
    now = int(time.time())
    today = A._day_key(now)
    yest = A._day_key(now - 86400)
    older = A._day_key(now - 3 * 86400)
    older2 = A._day_key(now - 4 * 86400)
    assert A._compute_streak({"history_days": [today, yest]}) == 2
    assert A._compute_streak({"history_days": [yest]}) == 1
    assert A._compute_streak({"history_days": [older, older2]}) == 0  # broken
    assert A._compute_streak({"history_days": []}) == 0


# ---------------- catch-up ----------------

def test_catchup_queues_to_upcoming_school_days(client):
    now = int(time.time())
    today = A._day_key(now)
    A._save_doc({"day": today,
                 "missed": [{"subject": "Math", "topic": "Algebra", "day": A._day_key(now - 86400),
                             "minutes": 30, "source": "plan", "confidence": "red"}]})
    r = client.post("/api/catchup", json={})
    assert r.status_code == 200
    data = A._load_doc()
    assert data.get("scheduled"), "expected queued scheduled items"
    for s in data["scheduled"]:
        assert s["day"] > today
        assert A._day_status(s["day"])[0] == "school"


def test_catchup_redates_stale_scheduled(client):
    now = int(time.time())
    today = A._day_key(now)
    A._save_doc({"day": today,
                 "scheduled": [{"subject": "Math", "topic": "Old", "day": A._day_key(now - 86400),
                                "minutes": 30, "confidence": "yellow"}]})
    r = client.post("/api/catchup", json={})
    assert r.status_code == 200
    data = A._load_doc()
    assert data["scheduled"][0]["day"] > today


# ---------------- API guardrails ----------------

def test_plan_endpoint_tolerates_bad_duration(client):
    r = client.post("/api/plan", json={"topics": [{"subject": "Math", "topic": "Algebra",
                                                    "confidence": "red"}],
                                       "start": "17:00", "end": "19:00",
                                       "duration_h": "abc", "mode": "practice",
                                       "criterion": "A"})
    assert r.status_code == 200  # defaults instead of 500


def test_append_extends_existing_plan(client):
    r1 = client.post("/api/plan", json={"topics": [{"subject": "Math", "topic": "Algebra",
                                                     "confidence": "red"}],
                                        "start": "17:00", "end": "19:00",
                                        "duration_h": 2, "mode": "practice", "criterion": "A"})
    first_blocks = r1.get_json()["plan"]["blocks"]
    r2 = client.post("/api/plan", json={"topics": [{"subject": "Physics", "topic": "Waves",
                                                     "confidence": "green"}],
                                        "start": "17:00", "end": "19:00",
                                        "duration_h": 2, "mode": "practice", "criterion": "A",
                                        "append": True})
    plan = r2.get_json()["plan"]
    assert len(plan["blocks"]) == len(first_blocks) + 1
    assert [b for b in plan["blocks"] if b["type"] == "study"][0]["topic"] == "Algebra"
    assert plan["blocks"][-1]["topic"] == "Waves"
    assert plan["blocks"][-1]["start"] == plan["blocks"][0]["end"]


def test_replace_when_no_append(client):
    client.post("/api/plan", json={"topics": [{"subject": "Math", "topic": "Algebra",
                                               "confidence": "red"}],
                                   "start": "17:00", "end": "19:00",
                                   "duration_h": 2, "mode": "practice", "criterion": "A"})
    r = client.post("/api/plan", json={"topics": [{"subject": "Physics", "topic": "Waves",
                                                    "confidence": "green"}],
                                       "start": "17:00", "end": "19:00",
                                       "duration_h": 2, "mode": "practice", "criterion": "A"})
    plan = r.get_json()["plan"]
    assert [b["topic"] for b in plan["blocks"] if b["type"] == "study"] == ["Waves"]


def test_shift_cannot_cross_midnight(client):
    # 60-min block ending 23:30: +45 would cross midnight, +10 is safe.
    client.post("/api/plan", json={"topics": [{"subject": "Math", "topic": "Algebra",
                                               "confidence": "red"}],
                                   "start": "22:30", "end": "23:59",
                                   "duration_h": 1, "mode": "practice", "criterion": "A"})
    r = client.post("/api/blocks/adjust", json={"action": "shift", "offset": 45})
    assert r.status_code == 400
    r = client.post("/api/blocks/adjust", json={"action": "shift", "offset": 10})
    assert r.status_code == 200
    plan = r.get_json()["plan"]
    assert max(b["end"] for b in plan["blocks"]) <= 24 * 60 - 1


def test_blocks_endpoint_only_clears(client):
    client.post("/api/plan", json={"topics": [{"subject": "Math", "topic": "Algebra",
                                               "confidence": "red"}],
                                   "start": "17:00", "end": "19:00",
                                   "duration_h": 2, "mode": "practice", "criterion": "A"})
    assert client.post("/api/blocks", json={"id": "x", "status": "done"}).status_code == 400
    r = client.post("/api/blocks", json={"clear": True})
    assert r.status_code == 200
    assert A._load_doc()["plan"] is None
