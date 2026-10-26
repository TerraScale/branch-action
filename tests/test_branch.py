"""Offline contract fixtures: the only executable boundary is the forthcoming ts CLI."""
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE, TARGET, OTHER, PROJECT = [f"01ARZ3NDEKTSV4RRFFQ69G5FA{x}" for x in "VWXZ"]


def database(name, identity=SOURCE, parent=None):
    return dict(name=name, id=identity, projectId=PROJECT, branchedFrom=parent)


def namespace(repo="123", label="preview", source=SOURCE):
    digest = hashlib.sha256(f"{PROJECT}:{source}:{repo}:42:{label}\n".encode()).hexdigest()[:24]
    return f"pr-42-{digest}"


def fake_cli():
    args = sys.argv[2:]
    assert args.pop(0) == "--json"
    expected = None
    while args[0].startswith("-"):
        flag = args.pop(0)
        if flag == "-yes":
            continue
        value = args.pop(0)
        if flag == "-expected-id":
            expected = value
        else:
            assert flag == "-project" and value == PROJECT
    with open(os.environ["FIXTURE_STATE"], "r+") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        state = json.load(file)
        state["calls"].append(args + ([expected] if expected else []))
        command, rows, mode = args[1], state["rows"], state.get("mode")
        result, status = None, 0
        if command == "list":
            result = list(rows.values())
            if mode == "list-error":
                status = 1
            if mode == "duplicate-source":
                result.append(rows["app"])
            if mode == "wrong-list-type":
                result = {"items": result}
            if mode == "duplicate-id":
                result.append(database("unrelated", SOURCE))
            if mode == "cross-project":
                result.append(database("unrelated", OTHER) | {"projectId": OTHER})
            if mode == "malformed-unrelated":
                result.append(database("unrelated", "invalid"))
        elif command == "info":
            result = rows[args[2]].copy()
            if mode == "source-race" and args[2] == "app":
                result["id"] = OTHER
            if mode == "target-race" and args[2] != "app":
                result["id"] = OTHER
            if mode == "generation-race" and args[2].startswith("g-"):
                result["id"] = OTHER
            if mode == "confirm-fail" and args[2].startswith("g-"):
                status = 1
        elif command == "branch":
            if mode == "branch-source-race":
                rows[args[2]] = database(args[2], OTHER)
            if expected != rows[args[2]]["id"] or args[3] in rows or mode in ("quota", "old-branch-server-404"):
                status = 1
            else:
                identity = TARGET if args[3].startswith("pr-") and not state.get("serial") else f"01ARZ3NDEKTSV4RRFFQ69G5F{state.get('serial', 0):02d}"
                state["serial"] = state.get("serial", 0) + 1
                result = database(args[3], identity, rows[args[2]]["id"])
                rows[args[3]] = result
                if mode == "copy-fail":
                    status = 1
                if mode == "bad-response":
                    result = result | {"branchedFrom": OTHER}
        elif command == "delete":
            if mode == "delete-race":
                rows[args[2]] = database(args[2], OTHER, SOURCE)
            if (mode == "old-server-404" or expected != rows[args[2]]["id"] or
                    (mode == "partial-delete" and sum(call[1] == "delete" for call in state["calls"]) == 2)):
                status = 1
            else:
                del rows[args[2]]
        else:
            raise AssertionError(args)
        file.seek(0)
        json.dump(state, file)
        file.truncate()
    print("not-json" if command == "list" and mode == "malformed-list" else json.dumps(result))
    if command == "list" and mode == "multiple-roots":
        print("[]")
    if command == "branch" and mode == "cancel":
        os.kill(os.getppid(), signal.SIGTERM)
        status = 1
    sys.exit(status)


class Provenance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        binary = self.directory / ".local/bin/ts"
        binary.parent.mkdir(parents=True)
        binary.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(__file__)} --fake \"$@\"\n")
        binary.chmod(0o755)
        self.state = self.directory / "state.json"
        event = self.directory / "event.json"
        event.write_text(json.dumps(dict(number=42, pull_request=dict(base=dict(repo=dict(id=123))))))
        self.env = dict(os.environ, HOME=str(self.directory), PROJECT=PROJECT, DATABASE="app",
                        TERRASCALE_API_KEY="fixture-only",
                        BRANCH="", COMMAND="", EVENT_ACTION="opened", PR_NUMBER="42",
                        GITHUB_EVENT_NAME="pull_request", GITHUB_REPOSITORY_ID="123",
                        GITHUB_EVENT_PATH=str(event), FIXTURE_STATE=str(self.state))
        self.write([database("app")])

    def write(self, rows, mode=""):
        self.state.write_text(json.dumps(dict(rows={row["name"]: row for row in rows}, calls=[], mode=mode)))

    def read(self):
        return json.loads(self.state.read_text())

    def run_action(self, filename="output", **env):
        output = self.directory / filename
        if output.is_file():
            output.unlink()  # Each invocation models a fresh GitHub step output file.
        result = subprocess.run(["bash", str(ROOT / "branch.sh")],
                                env=dict(self.env, GITHUB_OUTPUT=str(output), **env), capture_output=True, text=True)
        return result.returncode, output.read_text() if output.is_file() else ""

    def assert_no_mutation(self):
        self.assertFalse(any(call[1] in ("delete", "branch") for call in self.read()["calls"]))

    def test_create_reuse_close_and_absent_close(self):
        self.assertEqual(self.run_action()[0], 0)
        self.assertIn(f"id={TARGET}", self.run_action()[1])
        self.assertEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        self.assertNotIn(namespace(), self.read()["rows"])
        self.assertEqual(self.run_action(EVENT_ACTION="closed")[0], 0)

    def test_source_target_wrong_parent_project_and_changed_source(self):
        for changes, mode in [({"id": SOURCE}, ""), ({"branchedFrom": None}, ""),
                              ({"branchedFrom": OTHER}, ""), ({"projectId": OTHER}, ""),
                              ({"id": "invalid"}, ""), ({}, "source-race"), ({}, "target-race")]:
            with self.subTest(changes=changes, mode=mode):
                target = database(namespace(), TARGET, SOURCE) | changes
                self.write([database("app"), target], mode)
                for verb in ("create", "delete"):
                    self.assertNotEqual(self.run_action(COMMAND=verb)[0], 0)
                self.assert_no_mutation()
        self.write([database(namespace())])
        self.assertNotEqual(self.run_action(DATABASE=namespace())[0], 0)
        self.assert_no_mutation()

    def test_labels_cannot_adopt_unrelated_same_lineage_names(self):
        self.write([database("app"), database("orders", OTHER, SOURCE)])
        status, output = self.run_action(BRANCH="orders")
        self.assertEqual(status, 0)
        self.assertIn(f"name={namespace(label='orders')}", output)
        self.assertEqual(self.read()["rows"]["orders"]["id"], OTHER)
        self.assertNotEqual(namespace(), namespace(repo="456"))

    def test_delete_race_requires_expected_id(self):
        self.write([database("app"), database(namespace(), TARGET, SOURCE)], "delete-race")
        self.assertNotEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        self.assertEqual(self.read()["rows"][namespace()]["id"], OTHER)
        self.assertEqual(self.read()["calls"][-1][-1], TARGET)

    def test_conditional_route_404_never_falls_back(self):
        self.write([database("app"), database(namespace(), TARGET, SOURCE)], "old-server-404")
        self.assertNotEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        self.assertEqual(self.read()["rows"][namespace()]["id"], TARGET)
        deletes = [call for call in self.read()["calls"] if call[1] == "delete"]
        self.assertEqual(deletes, [["db", "delete", namespace(), TARGET]])

    def test_concurrent_create_has_one_identity_and_no_delete(self):
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda n: self.run_action(filename=f"output{n}"), range(2)))
        self.assertTrue(any(status == 0 for status, _ in results))
        self.assertEqual(self.read()["rows"][namespace()]["id"], TARGET)
        self.assertFalse(any(call[1] == "delete" for call in self.read()["calls"]))

    def test_wrong_event_fails_before_cli(self):
        self.assertNotEqual(self.run_action(PR_NUMBER="43")[0], 0)
        self.assertEqual(self.read()["calls"], [])
        self.assertNotEqual(self.run_action(TERRASCALE_API_KEY="")[0], 0)
        self.assertEqual(self.read()["calls"], [])

    def test_failed_malformed_and_ambiguous_inventory_never_mutates(self):
        for mode in ("list-error", "malformed-list", "wrong-list-type", "duplicate-source",
                     "duplicate-id", "cross-project", "malformed-unrelated", "multiple-roots"):
            with self.subTest(mode=mode):
                self.write([database("app"), database(namespace(), TARGET, SOURCE)], mode)
                self.assertNotEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
                self.assertNotEqual(self.run_action(COMMAND="create")[0], 0)
                self.assertNotEqual(self.reset()[0], 0)
                self.assert_no_mutation()

    def test_distinct_sources_and_source_replacement_during_copy(self):
        self.write([database("app"), database("other", OTHER)])
        self.assertEqual(self.run_action()[0], 0)
        self.assertIn(f"name={namespace(source=OTHER)}", self.run_action(DATABASE="other")[1])
        self.assertIn(namespace(), self.read()["rows"])
        self.write([database("app")], "branch-source-race")
        self.assertNotEqual(self.run_action()[0], 0)
        self.assertEqual(list(self.read()["rows"]), ["app"])
        self.assertEqual(self.read()["calls"][-1][-1], SOURCE)

    def test_concurrent_close_never_deletes_source(self):
        self.write([database("app"), database(namespace(), TARGET, SOURCE)])
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda n: self.run_action(filename=f"close{n}", EVENT_ACTION="closed"), range(2)))
        self.assertEqual(self.read()["rows"], {"app": database("app")})
        deletes = [call for call in self.read()["calls"] if call[1] == "delete"]
        self.assertTrue(all(call[-1] == TARGET for call in deletes))

    def reset(self, **env):
        return self.run_action(**(dict(COMMAND="reset", GITHUB_RUN_ID="900", GITHUB_RUN_ATTEMPT="1") | env))

    def test_reset_generation_is_confirmed_and_retry_is_idempotent(self):
        old = database(namespace(), TARGET, SOURCE) | {"documents": ["old data"]}
        child = database("user-child", OTHER, TARGET)
        digest = namespace().split("-")[-1]
        unrelated = database(f"g-{digest}-r900-a1-backup", "01ARZ3NDEKTSV4RRFFQ69G5FB9", SOURCE)
        self.write([database("app"), old, child, unrelated])
        status, output = self.reset()
        self.assertEqual(status, 0)
        values = dict(line.split("=", 1) for line in output.splitlines())
        generation = values["name"]
        self.assertEqual(generation, f"g-{digest}-r900-a1")
        self.assertNotIn(values["id"], (SOURCE, TARGET))
        self.assertEqual(self.reset()[1], output)
        rows = self.read()["rows"]
        self.assertEqual(rows[namespace()], old)
        self.assertEqual(rows["user-child"], child)  # Descendant lineage still names the old ULID.
        self.assertEqual(rows[generation]["id"], values["id"])
        self.assertEqual(rows[generation]["branchedFrom"], SOURCE)
        self.assertFalse(any(call[1] == "delete" for call in self.read()["calls"]))
        self.assertEqual(self.run_action()[1].splitlines()[0], f"name={namespace()}")
        self.assertEqual([call for call in self.read()["calls"] if call[1] == "branch"],
                         [["db", "branch", "app", generation, SOURCE]])
        self.assertEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        self.assertEqual(self.read()["rows"], {"app": database("app"), "user-child": child,
                                             unrelated["name"]: unrelated})

    def test_reset_failures_preserve_old_identity_data_and_descendants(self):
        old = database(namespace(), TARGET, SOURCE) | {"documents": ["old data"], "scopedKeys": ["old key binding"]}
        child = database("user-child", OTHER, TARGET)
        prior = database(f"g-{namespace().split('-')[-1]}-r899-a1", "01ARZ3NDEKTSV4RRFFQ69G5FB9", SOURCE)
        for mode in ("quota", "copy-fail", "bad-response", "confirm-fail", "cancel", "source-race",
                     "branch-source-race", "old-branch-server-404"):
            with self.subTest(mode=mode):
                self.write([database("app"), old, child, prior], mode)
                status, output = self.reset()
                self.assertNotEqual(status, 0)
                self.assertEqual(output, "")
                self.assertEqual(self.read()["rows"][namespace()], old)
                self.assertEqual(self.read()["rows"]["user-child"], child)
                self.assertEqual(self.read()["rows"][prior["name"]], prior)
                self.assertFalse(any(call[1] == "delete" for call in self.read()["calls"]))

    def test_reset_output_failure_retains_both_databases(self):
        self.write([database("app"), database(namespace(), TARGET, SOURCE)])
        (self.directory / "blocked").mkdir()
        self.assertNotEqual(self.reset(filename="blocked")[0], 0)
        self.assertEqual(len(self.read()["rows"]), 3)
        self.assertEqual(self.read()["rows"][namespace()]["id"], TARGET)

    def test_concurrent_resets_get_distinct_names_and_ids(self):
        self.write([database("app"), database(namespace(), TARGET, SOURCE)])
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            outputs = list(pool.map(lambda n: self.run_action(filename=f"reset{n}", COMMAND="reset",
                               GITHUB_RUN_ID=str(900 + n), GITHUB_RUN_ATTEMPT="1"), range(2)))
        self.assertTrue(all(status == 0 for status, _ in outputs))
        values = [dict(line.split("=", 1) for line in output.splitlines()) for _, output in outputs]
        self.assertNotEqual(values[0]["name"], values[1]["name"])
        self.assertNotEqual(values[0]["id"], values[1]["id"])
        self.assertEqual(self.read()["rows"][namespace()]["id"], TARGET)

    def test_close_preflights_all_generations_before_deleting_any(self):
        digest = namespace().split("-")[-1]
        self.write([database("app"), database(namespace(), TARGET, SOURCE),
                    database(f"g-{digest}-r900-a1", OTHER, TARGET)])
        self.assertNotEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        self.assert_no_mutation()

    def test_new_attempt_creates_another_generation_and_retries_reuse_it(self):
        first_status, first = self.reset()
        second_status, second = self.reset(GITHUB_RUN_ATTEMPT="2")
        self.assertEqual((first_status, second_status), (0, 0))
        self.assertNotEqual(first, second)
        self.assertEqual(self.reset(GITHUB_RUN_ATTEMPT="2"), (0, second))
        self.assertEqual(len(self.read()["rows"]), 3)
        self.assertNotIn(namespace(), self.read()["rows"])

    def test_generations_stay_bound_to_source_repository_and_label(self):
        self.write([database("app"), database("other", OTHER)])
        original = self.reset()[1].splitlines()[0]
        other_source = self.reset(DATABASE="other")[1].splitlines()[0]
        other_label = self.reset(BRANCH="orders")[1].splitlines()[0]
        event = Path(self.env["GITHUB_EVENT_PATH"])
        event.write_text(json.dumps(dict(number=42, pull_request=dict(base=dict(repo=dict(id=456))))))
        status, output = self.reset(GITHUB_REPOSITORY_ID="456")
        self.assertEqual(status, 0)
        other_repo = output.splitlines()[0]
        self.assertEqual(len({original, other_source, other_label, other_repo}), 4)
        self.assertEqual(self.run_action(EVENT_ACTION="closed", GITHUB_REPOSITORY_ID="456")[0], 0)
        rows = self.read()["rows"]
        self.assertNotIn(other_repo.removeprefix("name="), rows)
        self.assertTrue(all(value.removeprefix("name=") in rows for value in (original, other_source, other_label)))

    def test_invalid_generation_identity_never_mutates(self):
        for run, attempt in (("", "1"), ("0", "1"), ("0900", "1"), ("900", "01"),
                             ("900", "0"), ("900", "x"), ("9" * 21, "1"), ("9" * 20, "9" * 20)):
            with self.subTest(run=run, attempt=attempt):
                self.write([database("app")])
                self.assertNotEqual(self.reset(GITHUB_RUN_ID=run, GITHUB_RUN_ATTEMPT=attempt)[0], 0)
                self.assert_no_mutation()

    def test_close_only_matches_exact_base_and_strict_generations(self):
        digest = namespace().split("-")[-1]
        traps = [f"g-{digest}-r0-a1", f"g-{digest}-r0900-a1", f"g-{digest}-r900-a01",
                 f"g-{digest}-r900-a1-extra", f"g-{'0' * 24}-r900-a1", f"{namespace()}-extra"]
        unrelated = [database(name, f"01ARZ3NDEKTSV4RRFFQ69G5FC{n}", SOURCE) for n, name in enumerate(traps)]
        self.write([database("app")] + unrelated)
        self.assertEqual(self.reset()[0], 0)
        self.assertEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        self.assertEqual(self.read()["rows"], {row["name"]: row for row in [database("app")] + unrelated})
        deletes = [call for call in self.read()["calls"] if call[1] == "delete"]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0][2], f"g-{digest}-r900-a1")

    def test_late_generation_preflight_failure_prevents_every_delete(self):
        generation = database(f"g-{namespace().split('-')[-1]}-r900-a1", "01ARZ3NDEKTSV4RRFFQ69G5FB1", SOURCE)
        self.write([database("app"), database(namespace(), TARGET, SOURCE), generation], "generation-race")
        self.assertNotEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        self.assert_no_mutation()

    def test_partial_cleanup_keeps_failed_generation_and_is_retryable(self):
        generation = database(f"g-{namespace().split('-')[-1]}-r900-a1", OTHER, SOURCE)
        self.write([database("app"), database(namespace(), TARGET, SOURCE), generation], "partial-delete")
        self.assertNotEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        state = self.read()
        self.assertEqual(state["rows"], {"app": database("app"), generation["name"]: generation})
        self.assertEqual([call for call in state["calls"] if call[1] == "delete"],
                         [["db", "delete", namespace(), TARGET], ["db", "delete", generation["name"], OTHER]])
        state["mode"] = ""
        self.state.write_text(json.dumps(state))
        self.assertEqual(self.run_action(EVENT_ACTION="closed")[0], 0)
        self.assertEqual(self.read()["rows"], {"app": database("app")})


if __name__ == "__main__":
    if sys.argv[1:] == ["--fake"] or "--fake" in sys.argv[1:2]:
        fake_cli()
    unittest.main()
