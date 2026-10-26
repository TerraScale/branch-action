"""Offline contract fixtures: the only executable boundary is the forthcoming ts CLI."""
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
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
        elif command == "branch":
            if mode == "branch-source-race":
                rows[args[2]] = database(args[2], OTHER)
            if expected != rows[args[2]]["id"] or args[3] in rows:
                status = 1
            else:
                identity = TARGET if not state.get("serial") else "01ARZ3NDEKTSV4RRFFQ69G5FB0"
                state["serial"] = state.get("serial", 0) + 1
                result = database(args[3], identity, rows[args[2]]["id"])
                rows[args[3]] = result
        elif command == "delete":
            if mode == "delete-race":
                rows[args[2]] = database(args[2], OTHER, SOURCE)
            if mode == "old-server-404" or expected != rows[args[2]]["id"]:
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
        result = subprocess.run(["bash", str(ROOT / "branch.sh")],
                                env=dict(self.env, GITHUB_OUTPUT=str(output), **env), capture_output=True, text=True)
        return result.returncode, output.read_text() if output.exists() else ""

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


if __name__ == "__main__":
    if sys.argv[1:] == ["--fake"] or "--fake" in sys.argv[1:2]:
        fake_cli()
    unittest.main()
