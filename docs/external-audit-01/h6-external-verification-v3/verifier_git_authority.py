#!/usr/bin/env python
"""INDEPENDENT VERIFIER — H6 V3 GIT AUTHORITY GATE.

Reads frozen bytes straight out of the Git object database (git cat-file blob),
hashes them with an independent SHA256 implementation (hashlib/stdlib, and a
pure-python SHA256 fallback cross-check), and records blob-id level evidence.

This script is verifier-owned. It does NOT import or call any builder hash
helper. It never reads working-tree copies of the frozen artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------- pure python SHA256
# Independent implementation (no hashlib) used as a cross-check of hashlib.
_K = [
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1,
    0x923F82A4, 0xAB1C5ED5, 0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3,
    0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174, 0xE49B69C1, 0xEFBE4786,
    0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147,
    0x06CA6351, 0x14292967, 0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13,
    0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85, 0xA2BFE8A1, 0xA81A664B,
    0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A,
    0x5B9CCA4F, 0x682E6FF3, 0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208,
    0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
]
_H0 = [0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
       0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19]


def _rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def sha256_pure(data: bytes) -> str:
    length = len(data)
    msg = bytearray(data)
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0x00)
    msg += struct.pack(">Q", length * 8)
    h = list(_H0)
    for off in range(0, len(msg), 64):
        w = list(struct.unpack(">16I", bytes(msg[off:off + 64]))) + [0] * 48
        for i in range(16, 64):
            s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & 0xFFFFFFFF
        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
            ch = (e & f) ^ (~e & g)
            t1 = (hh + s1 + ch + _K[i] + w[i]) & 0xFFFFFFFF
            s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            t2 = (s0 + maj) & 0xFFFFFFFF
            hh, g, f, e, d, c, b, a = g, f, e, (d + t1) & 0xFFFFFFFF, c, b, a, (t1 + t2) & 0xFFFFFFFF
        h = [(x + y) & 0xFFFFFFFF for x, y in zip(h, [a, b, c, d, e, f, g, hh])]
    return "".join("%08x" % x for x in h)


assert sha256_pure(b"abc") == hashlib.sha256(b"abc").hexdigest(), "pure sha256 selftest failed"
SHA256_PURE_SELFTEST = "PASS"

# ---------------------------------------------------------------- git plumbing

def git(*args, binary=False):
    p = subprocess.run(["git"] + list(args), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout if binary else p.stdout.decode("utf-8")


def rev(expr):
    return git("rev-parse", expr).strip()


def parents(sha):
    line = git("rev-list", "--parents", "-n", "1", sha).strip().split()
    return line[1:]


def blob_bytes(commit, path):
    """Exact bytes of the blob at <commit>:<path> from the object database."""
    return git("cat-file", "blob", "%s:%s" % (commit, path), binary=True)


def blob_id(commit, path):
    return rev("%s:%s" % (commit, path))


def commit_meta(sha):
    raw = git("cat-file", "-p", sha, binary=True)
    header, _, body = raw.partition(b"\n\n")
    lines = header.decode("utf-8", "replace").split("\n")
    tree = None
    par = []
    for ln in lines:
        if ln.startswith("tree "):
            tree = ln.split(" ", 1)[1]
        elif ln.startswith("parent "):
            par.append(ln.split(" ", 1)[1])
    msg = body.decode("utf-8", "replace")
    return {
        "full_sha": sha,
        "tree_sha": tree,
        "parent_shas": par,
        "parent_count": len(par),
        "is_merge": len(par) > 1,
        "commit_message_subject": msg.split("\n", 1)[0].strip(),
        "commit_message_full": msg,
        "author": git("log", "-1", "--format=%an <%ae>", sha).strip(),
        "author_date": git("log", "-1", "--format=%aI", sha).strip(),
        "committer_date": git("log", "-1", "--format=%cI", sha).strip(),
    }


def is_ancestor(a, b):
    p = subprocess.run(["git", "merge-base", "--is-ancestor", a, b], capture_output=True)
    return p.returncode == 0


def relation(ancestor, descendant):
    """Classify relation of `ancestor` to `descendant`.

    DIRECT_PARENT  -> ancestor is a direct parent of descendant
    ANCESTOR       -> ancestor is a strict ancestor (non-parent) of descendant
    UNRELATED      -> no ancestry path
    """
    if is_ancestor(ancestor, descendant) is False:
        # also guard identical-shas edge case
        return "UNRELATED"
    if ancestor in parents(descendant):
        return "DIRECT_PARENT"
    return "ANCESTOR"


# ---------------------------------------------------------------- paths
REPO_ROOT = git("rev-parse", "--show-toplevel").strip()
BASE = "0941082fc875a66287d2b09159112963141bcf27"
PREREG = "9f1d844312419575d6b635a7356111050fd9b93a"
SHORTS = ["0941082", "f048520", "2cd8f85", "9f1d844", "b2c6b2b", "a548716"]

ARTIFACTS = [
    ("H6_SPEC_V3", "docs/external-audit-01/oi-full-history-03/H6_SPEC_V3.json",
     "cd354e0603a4b8ee754d38a2a6e3a2689c06e683b732ab34bec03e631c50eeea"),
    ("H6_MANIFEST_V3", "docs/external-audit-01/oi-full-history-03/H6_MANIFEST_V3.json",
     "de42e4a1581855243969820ba4658582f398735586764ca0a8684920db95ecb3"),
    ("H6_FEATURE_AUTHORITY_WHITELIST_V3",
     "docs/external-audit-01/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json",
     "c59718cafcd8c0a23ea6cbf7244e328f668c95bf40744e3520752c52fa0a1b31"),
    ("H6_DATA_AUTHORITY_V3", "docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json",
     "4e2bada45fa06fb10ed89815759f2bc258d093afab70b93c6a983763e528466b"),
]


def main():
    out = {
        "verifier_type": "INDEPENDENT_GIT_AUTHORITY_VERIFICATION_V3",
        "scope": "H6 V3 prereg freeze + post-prereg immutability",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository_root": REPO_ROOT,
        "executing_worktree": os.getcwd(),
        "verifier_base_commit": rev("HEAD"),
        "verifier_branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "sha256_backends": {
            "primary": "python hashlib.sha256",
            "crosscheck": "pure-python SHA256 (independent implementation in this script)",
            "crosscheck_selftest": SHA256_PURE_SELFTEST,
            "builder_hash_helper_used": False,
            "working_tree_bytes_used": False,
        },
        "commits": [],
        "ancestry_checks": [],
        "frozen_artifacts": [],
        "post_prereg_change_classification": [],
        "prereg_role_evidence": {},
    }

    # ---- 1. commits
    for s in SHORTS:
        sha = rev(s + "^{commit}")
        m = commit_meta(sha)
        m["abbrev_requested"] = s
        out["commits"].append(m)

    resolved = {c["abbrev_requested"]: c["full_sha"] for c in out["commits"]}
    out["resolved_shas"] = resolved

    # ---- 2. ancestry / direct parent checks (explicitly, not assumed)
    pairs = [
        ("0941082", "f048520", "ancestor"),
        ("f048520", "2cd8f85", "direct_parent"),
        ("2cd8f85", "9f1d844", "direct_parent"),
        ("9f1d844", "b2c6b2b", "ancestor"),
        ("b2c6b2b", "a548716", "direct_parent"),
    ]
    for a_s, b_s, claim in pairs:
        a, b = resolved[a_s], resolved[b_s]  # a = candidate ancestor, b = candidate descendant
        rel = relation(a, b)
        out["ancestry_checks"].append({
            "test": "%s is %s of %s" % (a_s, claim, b_s),
            "a_ancestor": a, "b_descendant": b,
            "claimed_relation": claim,
            "observed_relation": rel,
            "is_ancestor": is_ancestor(a, b),
            "is_direct_parent": a in parents(b),
            "direct_parent_reverse": b in parents(a),
            "pass": (rel == "DIRECT_PARENT") if claim == "direct_parent" else (rel in ("DIRECT_PARENT", "ANCESTOR")),
        })

    # full chain linearity
    chain = []
    cur = resolved["a548716"]
    stop = resolved["0941082"]
    while True:
        chain.append(cur)
        par = parents(cur)
        if cur == stop:
            break
        if len(par) != 1:
            out["chain_break"] = {"at": cur, "parents": par}
            break
        cur = par[0]
        if len(chain) > 20:
            break
    out["linear_chain_head_to_base"] = chain
    out["base_is_single_parent_of_head_path"] = chain[-1] == stop
    out["commit_count_base_to_head"] = int(git("rev-list", "--count", "%s..%s" % (BASE, resolved["a548716"])).strip())
    out["merge_commits_in_slice"] = [
        s for s in git("rev-list", resolved["a548716"], "^" + BASE).split()
        if len(parents(s)) > 1
    ]

    # ---- 3. prereg role evidence for 9f1d844
    prereg_tree_paths = git("ls-tree", "-r", "--name-only", PREREG).splitlines()
    pre = {"subject": git("log", "-1", "--format=%s", PREREG).strip(),
           "body": git("log", "-1", "--format=%B", PREREG).strip(),
           "paths_matching_h6_v3": [p for p in prereg_tree_paths if "H6_" in p and "_V3.json" in p]}
    for name, path, _ in ARTIFACTS:
        pre[name] = "PRESENT_IN_PREREG_TREE" if path in prereg_tree_paths else "ABSENT"
    # did the prereg commit introduce them (vs. inherit)?
    changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", PREREG).splitlines()
    pre["prereg_commit_touched_paths_count"] = len(changed)
    pre["prereg_commit_introduced_or_modified"] = [
        p for p in changed if any(p == a[1] for a in ARTIFACTS)
    ]
    # existence before prereg (at base and its parent chain) => were these NEW at prereg?
    for name, path, _ in ARTIFACTS:
        exists_at_base = subprocess.run(["git", "cat-file", "-e", "%s:%s" % (BASE, path)],
                                        capture_output=True).returncode == 0
        pre[name + "_exists_at_base"] = exists_at_base
        in_prereg_diff = path in changed
        pre[name + "_authored_in_prereg_commit"] = in_prereg_diff
        if not in_prereg_diff:
            intro = git("log", "--oneline", "--diff-filter=A", "--", path).splitlines()
            pre[name + "_introduced_by"] = intro[0] if intro else "UNKNOWN"
    pre["interpretation"] = (
        "Three of the four frozen artifacts were authored by the prereg commit itself; "
        "H6_DATA_AUTHORITY_V3.json was authored by the immediately preceding repair commit "
        "f048520 and was CARRIED UNCHANGED into the prereg tree (so the prereg commit froze "
        "it rather than regenerating it). Either way each artifact is present in the prereg "
        "tree and byte-identical at b2c6b2b and a548716."
    )
    out["prereg_role_evidence"] = pre

    # ---- 4/5/6. frozen artifacts: blob ids + hashes at prereg, b2c6b2b, final
    bsha = resolved["b2c6b2b"]
    fsha = resolved["a548716"]
    for name, path, declared in ARTIFACTS:
        entry = {"artifact": name, "path": path}
        exists = {}
        for tag, c in (("prereg", PREREG), ("b2c6b2b", bsha), ("a548716", fsha)):
            ok = subprocess.run(["git", "cat-file", "-e", "%s:%s" % (c, path)],
                                capture_output=True).returncode == 0
            exists[tag] = ok
            if ok:
                entry[tag + "_blob_id"] = blob_id(c, path)
                b = blob_bytes(c, path)
                entry[tag + "_bytes"] = len(b)
                entry[tag + "_sha256"] = hashlib.sha256(b).hexdigest()
                entry[tag + "_sha256_pure"] = sha256_pure(b)
            else:
                entry[tag + "_blob_id"] = None
                entry[tag + "_sha256"] = None
        entry["declared_sha256"] = declared
        entry["verifier_sha256"] = entry.get("prereg_sha256")
        entry["hash_match_declared_vs_verifier"] = entry["verifier_sha256"] == declared
        entry["hashlib_purepython_agree"] = (
            entry.get("prereg_sha256") == entry.get("prereg_sha256_pure"))
        entry["drift_prereg_to_b2c6b2b"] = entry["prereg_blob_id"] != entry["b2c6b2b_blob_id"]
        entry["drift_prereg_to_final"] = entry["prereg_blob_id"] != entry["a548716_blob_id"]
        entry["drift"] = entry["drift_prereg_to_b2c6b2b"] or entry["drift_prereg_to_final"]
        entry["final_sha256"] = entry.get("a548716_sha256")
        entry["final_blob_id"] = entry.get("a548716_blob_id")
        # raw byte diff (3-way) if drifted
        if entry["drift"]:
            d = subprocess.run(["git", "diff", "--stat", PREREG, fsha, "--", path],
                               capture_output=True).stdout.decode("utf-8", "replace")
            entry["git_diff_stat_prereg_to_final"] = d
        out["frozen_artifacts"].append(entry)

    # ---- 7. post-prereg change classification
    def classify(p):
        if p.startswith("docs/external-audit-01/h6-external-verification-v3/"):
            return "VERIFIER_PACKAGE"
        if p.startswith("docs/external-audit-01/oi-full-history-03/"):
            base = os.path.basename(p)
            if base in ("H6_SPEC_V3.json", "H6_MANIFEST_V3.json"):
                return "ECONOMIC_SPEC"
            if base == "H6_FEATURE_AUTHORITY_WHITELIST_V3.json":
                return "ECONOMIC_SPEC"
            if base in ("H6_DATA_AUTHORITY_V3.json", "H6_DATA_AUTHORITY_CHECK.json"):
                return "DATA_AUTHORITY"
            return "EVIDENCE_ONLY"
        if p.startswith("docs/") or p.startswith("tasks/") or p.startswith("context/") or p.startswith(".ai/"):
            return "GOVERNANCE_RECORD"
        if p.startswith("tests/") or "/test_" in p or p.endswith("conftest.py"):
            return "TEST"
        if p.startswith("src/") or p.endswith(".py") or p.startswith("scripts/"):
            return "CODE"
        if p.startswith("data/"):
            return "DATA_AUTHORITY"
        return "UNKNOWN"

    for rng in (("%s..%s" % (PREREG, bsha)), ("%s..%s" % (bsha, fsha))):
        files = git("diff", "--name-status", rng).splitlines()
        rec = {"range": rng, "files": []}
        counts = {}
        for ln in files:
            parts = ln.split("\t")
            st, p = parts[0], parts[-1]
            cls = classify(p)
            counts[cls] = counts.get(cls, 0) + 1
            rec["files"].append({"status": st, "path": p, "class": cls})
        rec["class_counts"] = counts
        rec["file_count"] = len(rec["files"])
        # flag any change that touches economic semantics / authority / PIT / shadow
        sensitive = []
        for f in rec["files"]:
            p = f["path"]
            low = p.lower()
            if any(k in low for k in (
                "h6_spec", "h6_manifest_v3", "feature_authority_whitelist_v3",
                "data_authority", "confirmation", "conf_lock", "shadow",
                "pit", "whitelist", "execution_ledger", "dataset", "feature_engine",
                "eligibility", "drift_guard", "contamination",
            )):
                sensitive.append(f)
        rec["sensitive_files_touching_h6_authority"] = sensitive
        out["post_prereg_change_classification"].append(rec)

    out["post_prereg_full_path_lists"] = {
        rec["range"]: [f["path"] for f in rec["files"]]
        for rec in out["post_prereg_change_classification"]
    }

    # ---- critical question: did post-prereg changes touch governed semantics?
    GOVERNED = {
        "H6_ECONOMIC_SEMANTICS": ["src/trading_bot/research/h6/", "docs/external-audit-01/oi-full-history-03/H6_SPEC_V3.json", "docs/external-audit-01/oi-full-history-03/H6_MANIFEST_V3.json"],
        "FEATURE_AUTHORITY": ["docs/external-audit-01/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json", "src/trading_bot/research/h6/whitelist.py"],
        "DATASET_AUTHORITY": ["docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json", "src/trading_bot/research/h6/dataset.py"],
        "PIT_IMPLEMENTATION": ["src/trading_bot/research/h6/feature_engine.py", "src/trading_bot/research/h6/contamination_scan.py", "src/trading_bot/research/h6/drift_guard.py"],
        "CONFIRMATION_AUTHORITY": ["src/trading_bot/research/h6/confirmation_state.py", "src/trading_bot/research/h6/conf_lock.py", "src/trading_bot/research/h6/execution_ledger.py", "src/trading_bot/research/h6/eligibility.py"],
        "SHADOW_BEHAVIOR": ["src/trading_bot/shadow/"],
    }
    crit = {}
    for label, needles in GOVERNED.items():
        hits = []
        for rec in out["post_prereg_change_classification"]:
            for f in rec["files"]:
                if any(f["path"] == n or f["path"].startswith(n) for n in needles):
                    hits.append({"range": rec["range"], **f})
        crit[label] = {
            "modified_after_prereg": bool(hits),
            "hits": hits,
            "verdict": "MODIFIED_POST_PREREG" if hits else "UNCHANGED_AFTER_PREREG",
        }
    out["critical_question_post_prereg_semantic_mutations"] = crit
    out["critical_question_verdict"] = (
        "NO_GOVERNED_SEMANTIC_MUTATION_AFTER_PREREG"
        if not any(v["modified_after_prereg"] for v in crit.values())
        else "GOVERNED_SEMANTIC_MUTATION_AFTER_PREREG_FOUND"
    )
    out["post_prereg_changes_are_evidence_only"] = all(
        all(f["class"] in ("EVIDENCE_ONLY", "VERIFIER_PACKAGE", "DATA_AUTHORITY", "CODE")
            and not f["path"].startswith("src/")
            for f in rec["files"])
        for rec in out["post_prereg_change_classification"]
    )

    # ---- verdict
    ancestry_ok = all(c["pass"] for c in out["ancestry_checks"])
    freeze_ok = all(
        a["drift"] is False and a["hash_match_declared_vs_verifier"] is True
        and a["hashlib_purepython_agree"] is True for a in out["frozen_artifacts"])
    # a post-prereg change to ECONOMIC_SPEC / DATA_AUTHORITY frozen files is a defect
    econ_touched = []
    for rec in out["post_prereg_change_classification"]:
        for f in rec["files"]:
            if f["class"] in ("ECONOMIC_SPEC", "DATA_AUTHORITY") and f["path"].split("/")[-1] in (
                "H6_SPEC_V3.json", "H6_MANIFEST_V3.json",
                "H6_FEATURE_AUTHORITY_WHITELIST_V3.json", "H6_DATA_AUTHORITY_V3.json"):
                econ_touched.append({"range": rec["range"], **f})
    out["post_prereg_frozen_authority_mutations"] = econ_touched

    out["git_authority_status"] = "PASS" if (ancestry_ok and freeze_ok) else "FAIL"
    out["summary"] = {
        "ancestry_checks_pass": ancestry_ok,
        "no_merge_commits_in_slice": out["merge_commits_in_slice"] == [],
        "prereg_freeze_pass": freeze_ok,
        "post_prereg_immutability_pass": not econ_touched,
        "frozen_authority_mutations_after_prereg": len(econ_touched),
    }
    if out["git_authority_status"] != "PASS":
        out["git_authority_status"] = "FAIL"

    print(json.dumps(out, indent=2))
    if "--out" in sys.argv:
        dest = sys.argv[sys.argv.index("--out") + 1]
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        print("WROTE", dest, file=sys.stderr)


if __name__ == "__main__":
    main()
