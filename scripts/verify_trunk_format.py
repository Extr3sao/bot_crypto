#!/usr/bin/env python
"""Prove that a formatting-only commit changed nothing but representation.

The verifier never looks at a working tree: it reads the before side from the base
commit and the after side from the head commit, both through ``git cat-file``. A
clean checkout of the head commit therefore reproduces every number below, which a
working-tree comparison could not.

What it asserts, per changed file:

* the path is Python and exists on both sides (no file added, renamed or deleted);
* ``ast.dump`` without attributes is identical, so no name, literal, operator or
  call changed;
* the sequence of comment tokens is identical (a formatter may not drop, move or
  reword a comment);
* control comments (``noqa``, ``type: ignore``, ``pragma``, ``fmt: off/on/skip``,
  ``nosec``, ``no cover``, ``mypy:``) are preserved one for one;
* adjacent string literals are merged before they are compared, and each pair is
  evaluated. A rewrite whose value is unchanged (quote style, an f-string whose
  inner quotes were inverted, implicit concatenation joined onto one line) is
  counted as representation; a rewrite whose value changed is a failure.

One difference cannot be avoided and is therefore declared, not hidden. Ruff strips
trailing whitespace inside docstrings, and a docstring *value* is an AST constant, so
the two acceptance criteria "the formatter gate passes" and "every AST is identical"
are mutually exclusive for a file that ends a docstring line with a space. The
verifier proves the exception is confined to docstrings and to whitespace, enumerates
every occurrence, and reports ``strict_ast_equality`` separately from the verdict.

Usage::

    python scripts/verify_trunk_format.py --base <sha> --head <sha> \
        --expect-files 433 --json <out>.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

CONTROL_PATTERNS = (
    r"#\s*noqa\b",
    r"#\s*type:\s*ignore\b",
    r"#\s*pragma\b",
    r"#\s*fmt:\s*(?:off|on|skip)\b",
    r"#\s*nosec\b",
    r"#\s*no\s*cover\b",
    r"#\s*mypy:",
)
CONTROL_RE = re.compile("|".join(CONTROL_PATTERNS), re.IGNORECASE)
# Tokens that sit *between* two literals without ending an implicit concatenation.
_ADJACENCY_TRANSPARENT = frozenset(
    {
        tokenize.NL,
        tokenize.COMMENT,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
    }
)
_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {message}")
    return proc.stdout


def blob(repo: Path, rev: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{rev}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def changed_files(repo: Path, base: str, head: str) -> list[tuple[str, str, str]]:
    raw = git(repo, "diff", "--name-status", "--no-renames", base, head).decode("utf-8")
    rows: list[tuple[str, str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        rows.append((parts[0], parts[1], parts[-1]))
    return rows


def comment_tokens(source: bytes) -> list[str]:
    return [
        tok.string
        for tok in tokenize.tokenize(io.BytesIO(source).readline)
        if tok.type == tokenize.COMMENT
    ]


def control_comments(comments: list[str]) -> Counter[str]:
    counted: Counter[str] = Counter()
    for comment in comments:
        match = CONTROL_RE.search(comment)
        if match:
            counted[re.sub(r"\s+", " ", match.group(0).strip().lower())] += 1
    return counted


def logical_strings(source: bytes) -> list[tuple[int, str]]:
    """Return (start line, text) per literal, with implicit concatenation merged."""
    out: list[tuple[int, str]] = []
    pending: str | None = None
    pending_line = 0
    previous_was_string = False
    for tok in tokenize.tokenize(io.BytesIO(source).readline):
        if tok.type == tokenize.STRING:
            if previous_was_string and pending is not None:
                pending = f"{pending} {tok.string}"
            else:
                if pending is not None:
                    out.append((pending_line, pending))
                pending = tok.string
                pending_line = tok.start[0]
            previous_was_string = True
        elif tok.type in _ADJACENCY_TRANSPARENT:
            continue
        else:
            if pending is not None:
                out.append((pending_line, pending))
                pending = None
            previous_was_string = False
    if pending is not None:
        out.append((pending_line, pending))
    return out


def expr_fingerprint(raw: str) -> str | None:
    """Fingerprint the *value* of a literal, so quote style cannot hide a change."""
    try:
        node = ast.parse(raw, mode="eval").body
    except SyntaxError:
        return None
    return ast.dump(node, include_attributes=False)


def expr_string_value(raw: str) -> str | None:
    """Return the value of a plain string literal, or None for an interpolated f-string."""
    try:
        node = ast.parse(raw, mode="eval").body
    except SyntaxError:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def ast_fingerprint(source: bytes) -> str:
    return hashlib.sha256(
        ast.dump(ast.parse(source), include_attributes=False).encode("utf-8")
    ).hexdigest()


def split_docstrings(source: bytes) -> tuple[list[tuple[int, str]], str]:
    """Return every docstring with its owner line, plus the AST fingerprint without them."""
    tree = ast.parse(source)
    docs: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docs.append((first.lineno, first.value.value))
            first.value = ast.Constant(value="", kind=None)
    return docs, hashlib.sha256(
        ast.dump(tree, include_attributes=False).encode("utf-8")
    ).hexdigest()


def whitespace_only(before: str, after: str) -> bool:
    """True when the two docstrings differ only by stripped trailing whitespace."""
    return [line.rstrip() for line in before.splitlines()] == [
        line.rstrip() for line in after.splitlines()
    ]


def analyse_file(
    repo: Path, base: str, head: str, old_path: str, path: str, status: str
) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": path, "status": status}
    before = blob(repo, base, old_path)
    after = blob(repo, head, path)
    entry["sha256_before"] = hashlib.sha256(before).hexdigest() if before else None
    entry["sha256_after"] = hashlib.sha256(after).hexdigest() if after else None
    entry["bytes_before"] = len(before) if before else 0
    entry["bytes_after"] = len(after) if after else 0
    entry["bytes_changed"] = (before != after) if before is not None and after is not None else None
    if before is None or after is None:
        entry["problems"] = ["missing_side"]
        return entry

    try:
        entry["ast_equal"] = ast_fingerprint(before) == ast_fingerprint(after)
        docs_before, fp_before = split_docstrings(before)
        docs_after, fp_after = split_docstrings(after)
    except SyntaxError as exc:
        entry["ast_equal"] = False
        entry["problems"] = [f"unparsable:{exc.msg}"]
        return entry

    entry["ast_equal_without_docstrings"] = fp_before == fp_after
    entry["docstrings"] = len(docs_before)
    residuals: list[dict[str, Any]] = []
    if len(docs_before) != len(docs_after):
        residuals.append({"problem": "docstring_count_changed"})
    else:
        for (line, text_before), (_, text_after) in zip(docs_before, docs_after, strict=True):
            if text_before == text_after:
                continue
            residuals.append(
                {
                    "line": line,
                    "whitespace_only": whitespace_only(text_before, text_after),
                    "bytes_removed": len(text_before.encode()) - len(text_after.encode()),
                    "before_tail": text_before[-40:],
                    "after_tail": text_after[-40:],
                }
            )
    entry["docstring_residuals"] = residuals

    comments_before = comment_tokens(before)
    comments_after = comment_tokens(after)
    entry["comments_before"] = len(comments_before)
    entry["comments_after"] = len(comments_after)
    entry["comments_equal"] = comments_before == comments_after
    entry["control_before"] = dict(control_comments(comments_before))
    entry["control_preserved"] = control_comments(comments_before) == control_comments(
        comments_after
    )

    strings_before = logical_strings(before)
    strings_after = logical_strings(after)
    representation_only = 0
    declared_residual_match = 0
    residual_lines = {res.get("line") for res in residuals if res.get("whitespace_only")}
    content_changes: list[dict[str, str]] = []
    if len(strings_before) != len(strings_after):
        content_changes.append(
            {
                "problem": "literal_count_changed",
                "before": str(len(strings_before)),
                "after": str(len(strings_after)),
            }
        )
    else:
        for (line, text_before), (_, text_after) in zip(strings_before, strings_after, strict=True):
            if text_before == text_after:
                continue
            fp_lit_before = expr_fingerprint(text_before)
            fp_lit_after = expr_fingerprint(text_after)
            if fp_lit_before is not None and fp_lit_before == fp_lit_after:
                representation_only += 1
                continue
            value_before = expr_string_value(text_before)
            value_after = expr_string_value(text_after)
            if (
                value_before is not None
                and value_after is not None
                and line in residual_lines
                and whitespace_only(value_before, value_after)
            ):
                # This is the docstring literal whose residual is already declared above,
                # counted once here so the totals cannot disagree with the residuals.
                declared_residual_match += 1
                continue
            content_changes.append(
                {"line": str(line), "before": text_before[:60], "after": text_after[:60]}
            )
    entry["literals_before"] = len(strings_before)
    entry["literals_after"] = len(strings_after)
    entry["literal_representation_changes"] = representation_only
    entry["literal_declared_residual_matches"] = declared_residual_match
    entry["literal_content_changes"] = content_changes

    problems: list[str] = []
    if not entry["ast_equal"]:
        if not all(res.get("whitespace_only") for res in residuals) or not residuals:
            problems.append("ast_differs")
        else:
            problems.append("ast_differs_docstring_whitespace")
    if not entry["comments_equal"]:
        problems.append("comments_differ")
    if not entry["control_preserved"]:
        problems.append("control_comments_lost")
    if content_changes:
        problems.append("literal_content_changed")
    if problems:
        entry["problems"] = problems
    return entry


def analyse(repo: Path, base: str, head: str, expect_files: int | None) -> dict[str, Any]:
    rows = changed_files(repo, base, head)
    added = [p for s, _, p in rows if s.startswith("A")]
    deleted = [p for s, _, p in rows if s.startswith("D")]
    renamed = [f"{o}->{p}" for s, o, p in rows if s.startswith("R")]
    non_python = [p for _, _, p in rows if not p.endswith(".py")]

    files = [analyse_file(repo, base, head, old, new, status) for status, old, new in rows]
    python_files = [
        row for row in files if row["path"].endswith(".py") and row.get("status") != "D"
    ]

    totals: Counter[str] = Counter()
    residuals: list[dict[str, Any]] = []
    for row in python_files:
        totals["files"] += 1
        totals["ast_equal"] += int(bool(row.get("ast_equal")))
        totals["ast_equal_without_docstrings"] += int(bool(row.get("ast_equal_without_docstrings")))
        totals["comments_equal"] += int(bool(row.get("comments_equal")))
        totals["control_preserved"] += int(bool(row.get("control_preserved")))
        totals["literal_representation"] += int(row.get("literal_representation_changes") or 0)
        totals["literal_declared"] += int(row.get("literal_declared_residual_matches") or 0)
        totals["literal_content"] += len(row.get("literal_content_changes") or [])
        totals["bytes_changed"] += int(bool(row.get("bytes_changed")))
        totals["comment_tokens"] += int(row.get("comments_before") or 0)
        totals["docstrings"] += int(row.get("docstrings") or 0)
        for residual in row.get("docstring_residuals") or []:
            residuals.append({"path": row["path"], **residual})

    strict_ok = bool(python_files) and totals["ast_equal"] == totals["files"]
    residual_ok = all(residual.get("whitespace_only") for residual in residuals)
    checks = [
        {
            "check": "only_python_changed",
            "ok": not non_python,
            "detail": f"every changed path ends in .py ({len(rows)})"
            if not non_python
            else f"non-Python paths: {non_python[:5]}",
        },
        {
            "check": "no_file_added_deleted_or_renamed",
            "ok": not (added or deleted or renamed),
            "detail": "no addition, deletion or rename"
            if not (added or deleted or renamed)
            else f"added={added[:5]} deleted={deleted[:5]} renamed={renamed[:5]}",
        },
        {
            "check": "ast_identical_strict",
            "ok": strict_ok,
            "detail": (
                f"{totals['ast_equal']}/{totals['files']} files byte-identical after "
                "ast.dump(include_attributes=False)"
            ),
        },
        {
            "check": "ast_identical_modulo_docstring_whitespace",
            "ok": totals["ast_equal_without_docstrings"] == totals["files"] and residual_ok,
            "detail": (
                f"{totals['ast_equal_without_docstrings']}/{totals['files']} identical once "
                f"docstring values are excluded; {len(residuals)} residual(s), whitespace_only="
                f"{residual_ok}"
            ),
        },
        {
            "check": "comments_identical",
            "ok": totals["comments_equal"] == totals["files"],
            "detail": f"{totals['comment_tokens']} comment tokens identical in order and text",
        },
        {
            "check": "control_comments_preserved",
            "ok": totals["control_preserved"] == totals["files"],
            "detail": "every noqa / type: ignore / pragma / fmt / nosec / no cover / mypy: survives",
        },
        {
            "check": "literals_representation_only",
            "ok": totals["literal_content"] == 0 and totals["literal_declared"] == len(residuals),
            "detail": (
                f"{totals['literal_representation']} literal rewrites with an unchanged value, "
                f"{totals['literal_declared']} covered by a declared residual, "
                f"{totals['literal_content']} with a changed value"
            ),
        },
        {
            "check": "changed_file_count_matches_inventory",
            "ok": expect_files is None or len(python_files) == expect_files,
            "detail": f"{len(python_files)} changed"
            + ("" if expect_files is None else f", expected {expect_files}"),
        },
    ]

    hard_failures = [
        row for row in checks if not row["ok"] and row["check"] != "ast_identical_strict"
    ]
    if hard_failures:
        verdict = "FAIL"
    elif strict_ok:
        verdict = "PASS"
    else:
        verdict = "PASS_WITH_DECLARED_RESIDUAL"

    return {
        "schema": "wp00307-trunk-format-evidence/1",
        "base": base,
        "head": head,
        "method": (
            "both sides read from git objects (git cat-file blob <rev>:<path>); the AST is "
            "compared with include_attributes=False so a line or column move is ignored by "
            "construction while a real change is not"
        ),
        "summary": {
            "files": totals["files"],
            "ast_equal_strict": totals["ast_equal"],
            "ast_equal_without_docstrings": totals["ast_equal_without_docstrings"],
            "comments_equal": totals["comments_equal"],
            "control_comments_preserved": totals["control_preserved"],
            "comment_tokens": totals["comment_tokens"],
            "docstrings": totals["docstrings"],
            "literal_representation_changes": totals["literal_representation"],
            "literal_declared_residuals": totals["literal_declared"],
            "literal_content_changes": totals["literal_content"],
            "bytes_changed": totals["bytes_changed"],
            "docstring_residuals": len(residuals),
        },
        "checks": checks,
        "residuals": residuals,
        "verdict": verdict,
        "files": files,
    }


def _run(
    repo: Path,
    args: list[str],
    env: dict[str, str] | None = None,
    payload: bytes | None = None,
) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
        env=env,
        input=payload,
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {message}")
    return proc.stdout


def synthesise(repo: Path, base: str, path: str, payload: bytes, add: bool = False) -> str:
    """Build a dangling commit identical to ``base`` except for one file."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _run(repo, ["read-tree", base], env)
        blob_sha = _run(repo, ["hash-object", "-w", "--stdin"], env, payload).decode().strip()
        flags = ["--add"] if add else []
        _run(
            repo,
            ["update-index", *flags, "--cacheinfo", f"100644,{blob_sha},{path}"],
            env,
        )
        tree = _run(repo, ["write-tree"], env).decode().strip()
        return (
            _run(repo, ["commit-tree", tree, "-p", base, "-m", "negative control"], env)
            .decode("utf-8")
            .strip()
        )


def self_test(repo: Path, base: str) -> int:
    """Show that each control actually fires, so a green run means something."""
    probes: list[tuple[str, str, Callable[[bytes], bytes], str]] = [
        (
            "nothing_changed",
            "verdict",
            lambda raw: raw,
            "a base compared with itself must not pass",
        ),
        (
            "semantic_addition",
            "ast_identical_strict",
            lambda raw: raw + b"\nNEGATIVE_CONTROL = 1\n",
            "an added assignment must break AST equality",
        ),
        (
            "comment_added",
            "comments_identical",
            lambda raw: raw + b"\n# NEGATIVE CONTROL\n",
            "an added comment must break comment equality",
        ),
        (
            "control_comment_added",
            "control_comments_preserved",
            lambda raw: raw + b"\nNEGATIVE_CONTROL = 1  # noqa: E501\n",
            "an added noqa must be noticed",
        ),
        (
            "literal_changed",
            "literals_representation_only",
            lambda raw: raw.replace(b'"utf-8"', b'"utf-9"', 1),
            "a changed literal value must not be waved through",
        ),
    ]
    target = "scripts/sprint002_lib.py"
    original = blob(repo, base, target)
    if original is None:
        print(f"[self-test] cannot read {target} at {base}", file=sys.stderr)
        return 2
    if b'"utf-8"' not in original:
        print(f'[self-test] {target} has no "utf-8" literal to mutate', file=sys.stderr)
        return 2

    results = []
    failures = 0
    for name, control, transform, why in probes:
        if name == "nothing_changed":
            record = analyse(repo, base, base, 433)
        else:
            head = synthesise(repo, base, target, transform(original))
            record = analyse(repo, base, head, 433)
        row = {row["check"]: row for row in record["checks"]}
        if control == "verdict":
            rejected = record["verdict"] == "FAIL"
        elif control == "literal_changed":
            rejected = any(
                entry.get("literal_content_changes")
                for entry in record["files"]
                if entry["path"] == target
            )
        else:
            rejected = not row[control]["ok"]
        failures += 0 if rejected else 1
        results.append({"control": name, "detected_by": control, "rejected": rejected, "why": why})
        print(f"[{'OK  ' if rejected else 'FAIL'}] {name}: detected_by={control}")

    added_tree = synthesise(repo, base, "scripts/NEGATIVE_CONTROL_ADDED.py", b"X = 1\n", add=True)
    record = analyse(repo, base, added_tree, 433)
    row = {row["check"]: row for row in record["checks"]}
    rejected = not row["no_file_added_deleted_or_renamed"]["ok"]
    failures += 0 if rejected else 1
    results.append(
        {
            "control": "file_added",
            "detected_by": "no_file_added_deleted_or_renamed",
            "rejected": rejected,
            "why": "a new file must not pass as a formatting-only change",
        }
    )
    print(
        f"[{'OK  ' if rejected else 'FAIL'}] file_added: detected_by=no_file_added_deleted_or_renamed"
    )

    print(f"[self-test] {len(results) - failures}/{len(results)} controls rejected their mutation")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a formatting-only commit.")
    parser.add_argument("--repo", default=".", help="repository to read (default: cwd)")
    parser.add_argument("--base", required=True, help="commit holding the pre-format state")
    parser.add_argument("--head", default="HEAD", help="commit holding the formatted state")
    parser.add_argument("--expect-files", type=int, default=None)
    parser.add_argument("--json", default=None, help="write the full record here")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="prove the controls fire by mutating the base commit into dangling probes",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test(Path(args.repo).resolve(), args.base)

    record = analyse(Path(args.repo).resolve(), args.base, args.head, args.expect_files)
    for row in record["checks"]:
        print(f"[{'OK  ' if row['ok'] else 'FAIL'}] {row['check']}: {row['detail']}")
    for residual in record["residuals"]:
        print(f"RESIDUAL {residual['path']}:{residual.get('line')} {residual}")
    print(f"VERDICT {record['verdict']} ({record['summary']['files']} files)")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[verify-trunk-format] wrote {out}")
    return 0 if record["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
