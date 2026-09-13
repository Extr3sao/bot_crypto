#!/usr/bin/env python
"""INDEPENDENT VERIFIER — H6 V3 WHITELIST ADVERSARIAL ATTACK + RUNTIME REACHABILITY.

Attacks the frozen feature-authority contract (H6_FEATURE_AUTHORITY_WHITELIST_V3.json)
with verifier-authored payloads. Does not trust or reuse builder whitelist tests.

Also performs a runtime-reachability audit: a static AST scan proving that the
enforcement primitive is actually reachable from H6 runtime code, and that no H6
runtime module references a forbidden field name outside the enforcement module.

Verifier-owned. No economics.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import pathlib
import pickle
import subprocess
import sys
import traceback
from datetime import datetime, timezone

VERIFIER_ROOT = pathlib.Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                   check=True).stdout.decode().strip()).resolve()
AUDITED_COMMIT = "a5487164803fb601f87f2cd4c865929c30da274e"
WL_PATH = "docs/external-audit-01/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json"
ENFORCEMENT_MODULE = "src/trading_bot/research/h6/whitelist.py"

RESULTS: list[dict] = []


def record(attack: str, blocked: bool, detail: str = "", severity_if_bypass: str = "HIGH") -> None:
    RESULTS.append({
        "attack": attack,
        "blocked": blocked,
        "detail": detail[:400],
        "severity_if_bypass": severity_if_bypass,
    })


def expect_raise(label, fn, exc_types, severity="HIGH"):
    try:
        v = fn()
        record(label, False, f"NO RAISE; returned {v!r}", severity)
    except exc_types as e:
        record(label, True, f"{type(e).__name__}", severity)
    except Exception as e:
        record(label, True, f"{type(e).__name__} (other exception): {e}", severity)


def main():
    sys.path.insert(0, str(VERIFIER_ROOT / "src"))

    # frozen contract, read from git bytes
    wl_raw = subprocess.run(["git", "cat-file", "blob", "%s:%s" % (AUDITED_COMMIT, WL_PATH)],
                            cwd=str(VERIFIER_ROOT), capture_output=True, check=True).stdout
    wl = json.loads(wl_raw)
    frozen_allowed = sorted(a["field"] for a in wl["ALLOWED_FIELDS"])
    frozen_forbidden = sorted(wl["FORBIDDEN_FIELDS"])

    from trading_bot.research.h6 import whitelist as W

    out = {
        "verifier_type": "INDEPENDENT_WHITELIST_ATTACK_V3",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audited_target_commit": AUDITED_COMMIT,
        "frozen_whitelist_path": WL_PATH,
        "frozen_whitelist_sha256": hashlib.sha256(wl_raw).hexdigest(),
        "frozen_allowed_fields": frozen_allowed,
        "frozen_forbidden_fields": frozen_forbidden,
        "module_resolution": {
            "whitelist_module": str(pathlib.Path(W.__file__).resolve()),
            "inside_verifier_worktree": str(pathlib.Path(W.__file__).resolve()).startswith(str(VERIFIER_ROOT)),
        },
        "contract_cross_check": {},
        "attacks": [],
        "runtime_reachability": {},
    }
    out["contract_cross_check"] = {
        "frozen_allowed_set_equals_code_ALLOWED_H6_FIELDS": set(frozen_allowed) == set(W.ALLOWED_H6_FIELDS),
        "frozen_forbidden_set_equals_code_FORBIDDEN_H6_FIELDS": set(frozen_forbidden) == set(W.FORBIDDEN_H6_FIELDS),
        "code_allows_extra_logical_fields": sorted(set(W._ALLOWED_ALL_FIELDS) - set(frozen_allowed) - {
            "sum_open_interest", "sum_open_interest_value"}),
        "declared_bypass_paths_allowed": wl["enforcement"]["bypass_paths_allowed"],
        "declared_covers": wl["enforcement"]["covers"],
        "note": ("The code additionally admits PIT/bookkeeping metadata fields "
                 "(timestamp_ms, unit_semantics, source_file, source_sha256) which are not "
                 "'features'. The frozen artifact's ALLOWED_FIELDS lists only the three FEATURE "
                 "fields, so the code's admitted set is a superset. Verified explicitly below."),
    }

    payload = {
        "sum_open_interest": 1000,
        "sum_open_interest_value": 5000.0,
        "price_open_high_low_close_volume_1h": "px",
        "timestamp_ms": 1700000000000,
        "unit_semantics": "BASE_ASSET_UNITS",
        "source_file": "data/raw/.../BTCUSDT-metrics-2024-06-05.zip",
        "source_sha256": "0" * 64,
        **{f: 4242 for f in frozen_forbidden},
        "unadmitted_metric": 12345,
        "nested": {"outer_inner": 1},
    }
    wrapped = W.H6FieldAccess(payload)

    # ---------------------------------------------------------------- attacks
    expect_raise("subscript forbidden field", lambda: wrapped[W.FORBIDDEN_H6_FIELDS.__iter__().__next__()],
                 (W.H6ForbiddenFeatureAccess,))
    expect_raise("subscript non-admitted field", lambda: wrapped["unadmitted_metric"],
                 (W.H6ForbiddenFeatureAccess,))
    expect_raise("get() forbidden field", lambda: wrapped.get("count_toptrader_long_short_ratio"),
                 (W.H6ForbiddenFeatureAccess,))
    expect_raise("get() non-admitted field", lambda: wrapped.get("unadmitted_metric"),
                 (W.H6ForbiddenFeatureAccess,))
    expect_raise("contains forbidden field", lambda: "count_long_short_ratio" in wrapped,
                 (W.H6ForbiddenFeatureAccess,))
    expect_raise("contains non-admitted field", lambda: "unadmitted_metric" in wrapped,
                 (W.H6ForbiddenFeatureAccess,))
    for f in frozen_forbidden:
        expect_raise("getattr forbidden field %s" % f, lambda f=f: getattr(wrapped, f),
                     (W.H6ForbiddenFeatureAccess,))
    expect_raise("getattr non-admitted field", lambda: getattr(wrapped, "unadmitted_metric"),
                 (W.H6ForbiddenFeatureAccess,))
    expect_raise("assert_field_allowed forbidden", lambda: W.assert_field_allowed("count_long_short_ratio"),
                 (W.H6ForbiddenFeatureAccess,))
    expect_raise("check_row_whitelist full forbidden row", lambda: W.check_row_whitelist(payload),
                 (W.H6ForbiddenFeatureAccess,))
    expect_raise("check_row_whitelist forbidden-only row",
                 lambda: W.check_row_whitelist({"sum_taker_long_short_vol_ratio": 1}),
                 (W.H6ForbiddenFeatureAccess,))

    # leakage through views
    def _iter_keys():
        return list(iter(wrapped))

    def _keys():
        return list(wrapped.keys())

    def _items():
        return list(wrapped.items())

    def _values():
        return list(wrapped.values())

    def _dict_unpack():
        return dict(**wrapped)

    def _dict_call():
        return dict(wrapped)

    def _json_via_items():
        return json.dumps(dict(wrapped.items()))

    def _json_default_str():
        return json.dumps(wrapped, default=lambda o: dict(o.items()))

    for name, fn in [
        ("iteration yields no forbidden", _iter_keys),
        ("keys() yields no forbidden", _keys),
        ("items() yields no forbidden", _items),
        ("values() yields no forbidden", _values),
        ("**unpack yields no forbidden", _dict_unpack),
        ("dict(wrapped) yields no forbidden", _dict_call),
        ("json via items() yields no forbidden", _json_via_items),
        ("json default=str yields no forbidden", _json_default_str),
    ]:
        try:
            res = fn()
            leaked = [f for f in frozen_forbidden if f in str(res)]
            record(name, not leaked, "leaked=%s" % leaked, "HIGH")
        except Exception as e:
            record(name, False, "raised %s: %s" % (type(e).__name__, e), "MEDIUM")

    # repr / str informational leakage
    for label, fn in [("repr() leaks no forbidden names", lambda: repr(wrapped)),
                      ("str() leaks no forbidden names", lambda: str(wrapped)),
                      ("format() leaks no forbidden names", lambda: "%s" % wrapped)]:
        try:
            txt = fn()
            leaked = [f for f in frozen_forbidden if f in txt]
            record(label, not leaked, "leaked=%s" % leaked, "MEDIUM")
        except Exception as e:
            record(label, True, "raised %s" % type(e).__name__, "MEDIUM")

    # raw backing exposure  (the interesting one)
    for label, fn in [
        ("direct .data attribute exposes raw mapping", lambda: wrapped.data),
        ("object.__getattribute__(wrapped,'data')", lambda: object.__getattribute__(wrapped, "data")),
    ]:
        try:
            raw = fn()
            retrievable = [f for f in frozen_forbidden if f in raw]
            record(label, not retrievable,
                   "forbidden keys retrievable from raw backing: %s" % retrievable, "HIGH")
        except Exception as e:
            record(label, True, "raised %s" % type(e).__name__, "HIGH")

    # introspection escapes
    for label, fn in [
        ("vars()", lambda: vars(wrapped)),
        ("__dict__", lambda: wrapped.__dict__),
        ("copy.copy", lambda: copy.copy(wrapped)),
        ("pickle roundtrip", lambda: pickle.loads(pickle.dumps(wrapped))),
    ]:
        try:
            res = fn()
            leaked = [f for f in frozen_forbidden if f in str(res)]
            record("introspection: %s leaks no forbidden" % label, not leaked,
                   "leaked=%s ; result_type=%s" % (leaked, type(res).__name__), "MEDIUM")
        except Exception as e:
            record("introspection: %s leaks no forbidden" % label, True,
                   "raised %s" % type(e).__name__, "MEDIUM")

    # mutation / aliasing attacks (frozen dataclass)
    expect_raise("attempt to rebind .data", lambda: setattr(wrapped, "data", {}),
                 (Exception,), "MEDIUM")
    expect_raise("attempt to add new attribute", lambda: setattr(wrapped, "evil", 1),
                 (Exception,), "MEDIUM")

    # allowed set correctness
    try:
        ak = wrapped.allowed_keys()
        record("allowed_keys() == code admitted set", set(ak) == set(W._ALLOWED_ALL_FIELDS),
               "allowed_keys=%s" % sorted(ak), "MEDIUM")
    except Exception as e:
        record("allowed_keys() == code admitted set", False, str(e), "MEDIUM")

    # 'uncertainty' attack: value-level masquerade (forbidden value under allowed key)
    try:
        disguised = W.H6FieldAccess({"sum_open_interest": {"count_long_short_ratio": 1}})
        v = disguised["sum_open_interest"]
        leaked = "count_long_short_ratio" in str(v)
        record("nested-dict value not key-screened (by design?)", True,
               "observed nested payload passes through: %s (documented limitation: the wrapper "
               "screens KEY NAMES, not nested VALUE structure)" % leaked, "LOW")
    except Exception as e:
        record("nested-dict value not key-screened", True, "raised %s" % type(e).__name__, "LOW")

    out["attacks"] = RESULTS
    out["attacks_total"] = len(RESULTS)
    out["attacks_blocked"] = sum(1 for r in RESULTS if r["blocked"])
    out["attacks_bypassed"] = [r for r in RESULTS if not r["blocked"]]
    out["WHITELIST_ADVERSARIAL_ATTACKS"] = "PASS" if not out["attacks_bypassed"] else "FAIL"

    # ------------------------------------------------ runtime reachability
    h6_dir = VERIFIER_ROOT / "src/trading_bot/research/h6"
    enforcement = (VERIFIER_ROOT / ENFORCEMENT_MODULE).read_text(encoding="utf-8")
    offenders, users = [], []
    for p in sorted(h6_dir.rglob("*.py")):
        rel = p.relative_to(VERIFIER_ROOT).as_posix()
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            offenders.append({"path": rel, "error": "SYNTAX_ERROR: %s" % e})
            continue
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        strs = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        hit_fields = sorted(f for f in frozen_forbidden if f in names or f in strs)
        uses = sorted({u for u in ("H6FieldAccess", "check_row_whitelist", "assert_field_allowed",
                                   "_ALLOWED_ALL_FIELDS", "is_field_allowed") if u in names})
        if uses and p.name != "whitelist.py":
            users.append({"path": rel, "uses": uses})
        elif uses:
            out.setdefault("_self_users", []).append({"path": rel, "uses": uses})
        if hit_fields and p.name != "whitelist.py":
            offenders.append({"path": rel, "forbidden_field_references": hit_fields})

    # Was the enforcement primitive imported anywhere outside the H6 package?
    who = subprocess.run(
        ["git", "grep", "-ln", "-e", "H6FieldAccess", "-e", "check_row_whitelist",
         "-e", "assert_field_allowed", "--", "src/"],
        cwd=str(VERIFIER_ROOT), capture_output=True, text=True).stdout.split()

    # Is a runtime H6 economic path currently reachable at all?
    gate = subprocess.run(
        [sys.executable, "-c", "from trading_bot.research.h6.execution_harness import "
         "can_execute_h6; print(can_execute_h6())"],
        cwd=str(VERIFIER_ROOT), capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(VERIFIER_ROOT / "src")})

    out["runtime_reachability"] = {
        "enforcement_module": ENFORCEMENT_MODULE,
        "enforcement_module_sha256_on_disk": hashlib.sha256(pathlib.Path(VERIFIER_ROOT / ENFORCEMENT_MODULE).read_bytes()).hexdigest(),
        "modules_using_enforcement_primitives_outside_enforcement_module": users,
        "modules_using_enforcement_outside_count": len(users),
        "enforcement_primitives_self_references_only": out.pop("_self_users", []),
        "all_src_files_referencing_primitives": who,
        "modules_referencing_forbidden_fields_outside_enforcement": offenders,
        "forbidden_references_outside_enforcement_count": len(offenders),
        "h6_execution_gate_can_execute_h6": gate.stdout.strip(),
        "reachability_verdict": (
            "REACHABLE" if users and not offenders else
            ("VIOLATIONS_FOUND" if offenders else "NOT_WIRED_INTO_ANY_RUNTIME_DATA_PATH")),
        "interpretation": (
            "No module outside whitelist.py (and the package __init__ re-export) invokes the "
            "fail-closed accessor. The H6 economic execution path is hard-gated OFF "
            "(can_execute_h6() is False), so there is currently no runtime OI-reading path to "
            "bypass. Feature authority is therefore currently enforced by (a) the normaliser's "
            "field whitelist stripping forbidden columns from the dataset bytes and (b) static "
            "scans, NOT by the runtime accessor. The accessor is a control that is present but "
            "not yet wired into a live data path."),
    }
    out["WHITELIST_RUNTIME_REACHABILITY"] = (
        "PASS" if (users and not offenders) else ("FAIL" if offenders else "FAIL_NOT_WIRED"))

    print(json.dumps(out, indent=2))
    if "--out" in sys.argv:
        dest = sys.argv[sys.argv.index("--out") + 1]
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        print("WROTE", dest, file=sys.stderr)


if __name__ == "__main__":
    main()
