"""G-149: Server-Timing header, first-party RUM collection point and the load trial script.

Expected values come from the G-149 text in src/data/requirements.json of the decision site:
first-party RUM with web-vitals, route templates and sampling, no third party, and
`Server-Timing` headers. These tests run without Frappe, so a fake `frappe` module stands in.
"""

import ast
import importlib
import re
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps" / "platform_core"
PACKAGE = APP / "platform_core"
HOOKS = PACKAGE / "hooks.py"
API = PACKAGE / "api" / "observability.py"
CONTRACT = ROOT / "contracts" / "platform_core-observability.openapi.yaml"
LOAD_TRIAL = ROOT / "dev" / "load" / "load_trial.py"
SERVER_TIMING = re.compile(r"app;dur=\d+(\.\d)?")
# Fields that would name or track a person. None of them may reach the RUM record.
PERSONAL_FIELDS = ("user", "email", "ip", "user_agent", "url", "session", "name", "full_name")


def fake_frappe():
    module = types.ModuleType("frappe")
    module.local = types.SimpleNamespace()
    module.ValidationError = type("ValidationError", (Exception,), {})
    module.throw = lambda message, exc=Exception: (_ for _ in ()).throw(exc(message))
    module._ = lambda text: text
    return module


class FakeHeaders:
    def __init__(self):
        self.items = []

    def add(self, name, value):
        self.items.append((name, value))

    def getlist(self, name):
        return [value for key, value in self.items if key.lower() == name.lower()]


class FakeResponse:
    def __init__(self):
        self.headers = FakeHeaders()


class ObservabilityTestCase(unittest.TestCase):
    def setUp(self):
        self.frappe = fake_frappe()
        self.saved = {name: sys.modules.get(name) for name in ("frappe",)}
        sys.modules["frappe"] = self.frappe
        sys.path.insert(0, str(APP))
        for name in list(sys.modules):
            if name.startswith("platform_core"):
                del sys.modules[name]

    def tearDown(self):
        sys.path.remove(str(APP))
        for name, module in self.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name in list(sys.modules):
            if name.startswith("platform_core"):
                del sys.modules[name]


class TestServerTiming(ObservabilityTestCase):
    def load(self):
        return importlib.import_module("platform_core.observability.server_timing")

    def test_response_carries_server_timing(self):
        timing = self.load()
        clock = iter((10.0, 10.0125))
        timing.start_request_timer(clock=lambda: next(clock))
        response = FakeResponse()
        timing.add_server_timing(response, clock=lambda: next(clock))
        values = response.headers.getlist("Server-Timing")
        self.assertEqual(values, ["app;dur=12.5"])
        self.assertRegex(values[0], SERVER_TIMING)

    def test_no_header_without_a_start_time(self):
        timing = self.load()
        response = FakeResponse()
        timing.add_server_timing(response)
        self.assertEqual(response.headers.getlist("Server-Timing"), [])

    def test_no_response_is_ignored(self):
        timing = self.load()
        timing.start_request_timer()
        timing.add_server_timing(None)

    def test_header_has_no_description_text(self):
        # A description could carry a route, a query or a name. Only the metric name and duration go out.
        self.assertEqual(self.load().format_server_timing({"app": 3.14159}), "app;dur=3.1")

    def test_hooks_register_the_timer(self):
        tree = ast.parse(HOOKS.read_text(encoding="utf-8"))
        lists = {
            node.targets[0].id: [element.value for element in node.value.elts if isinstance(element, ast.Constant)]
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.List)
        }
        start = "platform_core.observability.server_timing.start_request_timer"
        # The G-40 guard stays first (test_development_access_guard). The clock starts next.
        self.assertEqual(lists["before_request"][1], start)
        self.assertIn("platform_core.observability.server_timing.add_server_timing", lists["after_request"])


class TestRealUserMonitoring(ObservabilityTestCase):
    def load(self):
        return importlib.import_module("platform_core.observability.rum")

    def valid(self, **changes):
        beacon = {
            "route": "/panel/leave-application/:name",
            "metrics": {"LCP": 1840.5, "INP": 96, "CLS": 0.03, "FCP": 900, "TTFB": 210},
            "sample_rate": 0.1,
            "navigation_type": "navigate",
        }
        beacon.update(changes)
        return beacon

    def test_clean_beacon_keeps_only_allowed_fields(self):
        record = self.load().clean_beacon(self.valid())
        self.assertEqual(set(record), {"route", "metrics", "sample_rate", "navigation_type"})
        self.assertEqual(record["metrics"]["LCP"], 1840.5)

    def test_personal_fields_are_refused(self):
        rum = self.load()
        for field in PERSONAL_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(self.frappe.ValidationError):
                    rum.clean_beacon(self.valid(**{field: "ayse@example.test"}))

    def test_route_must_be_a_template(self):
        rum = self.load()
        for route in (
            "/panel/leave-application/HR-LAP-2026-00001",
            "/panel/user/ayse@example.test",
            "/panel/leave-application?employee=EMP-1",
            "/panel/leave-application#comment",
            "https://tenant.example.test/panel",
            "/panel/12",
            "panel",
            "/" + "a" * 300,
        ):
            with self.subTest(route=route):
                with self.assertRaises(self.frappe.ValidationError):
                    rum.clean_beacon(self.valid(route=route))

    def test_metric_names_and_ranges(self):
        rum = self.load()
        for metrics in (
            {},
            {"LCP": -1},
            {"LCP": float("nan")},
            {"LCP": 10**9},
            {"CLS": 500},
            {"LCP": "1000"},
            {"LCP": True},
            {"heap": 10},
        ):
            with self.subTest(metrics=metrics):
                with self.assertRaises(self.frappe.ValidationError):
                    rum.clean_beacon(self.valid(metrics=metrics))

    def test_sample_rate_and_navigation_type(self):
        rum = self.load()
        for changes in ({"sample_rate": 0}, {"sample_rate": 1.5}, {"navigation_type": "typed"}):
            with self.subTest(changes=changes):
                with self.assertRaises(self.frappe.ValidationError):
                    rum.clean_beacon(self.valid(**changes))
        record = rum.clean_beacon({"route": "/panel", "metrics": {"TTFB": 12}})
        self.assertEqual(record, {"route": "/panel", "metrics": {"TTFB": 12}, "sample_rate": 1.0})

    def test_endpoint_reads_no_person(self):
        # The collection point stores the cleaned beacon only. It never reads who sent it.
        source = API.read_text(encoding="utf-8")
        for marker in ("session", "remote_addr", "get_request_header", "user_agent", "frappe.local.request"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)
        tree = ast.parse(source)
        collect = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "collect_rum")
        decorators = {ast.unparse(d) for d in collect.decorator_list}
        self.assertTrue(any(d.startswith("frappe.whitelist(") and "POST" in d for d in decorators))
        self.assertTrue(any(d.startswith("rate_limit(") for d in decorators))

    def test_contract_lists_the_endpoint_and_metrics(self):
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("/platform_core.api.observability.collect_rum:", text)
        for name in self.load().METRICS:
            with self.subTest(metric=name):
                self.assertIn(name, text)
        self.assertIn("platform_core.api.observability.collect_rum", HOOKS.read_text(encoding="utf-8"))


class TestLoadTrial(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(LOAD_TRIAL), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def load(self):
        sys.path.insert(0, str(LOAD_TRIAL.parent))
        try:
            return importlib.import_module("load_trial")
        finally:
            sys.path.remove(str(LOAD_TRIAL.parent))

    def test_refuses_a_remote_target(self):
        for url in ("https://tenant.example.test", "http://10.0.0.5:8000", "http://localhost.evil.test"):
            with self.subTest(url=url):
                result = self.run_script("--base-url", url, "--requests", "1")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("local", result.stderr)

    def test_percentiles_and_server_timing_parse(self):
        trial = self.load()
        self.assertEqual(trial.percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(trial.percentile([1, 2, 3, 4], 95), 4)
        self.assertEqual(trial.server_duration("db;dur=2, app;dur=12.5"), 12.5)
        self.assertIsNone(trial.server_duration(None))

    def test_short_trial_against_a_local_server(self):
        result = self.run_script("--self-test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"p95_ms"', result.stdout)
        self.assertIn('"server_timing_missing": 0', result.stdout)


if __name__ == "__main__":
    unittest.main()
