import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from container_privileges import CAPABILITIES, CAP_FIELDS, compose_privileges, process_privileges


class PrivilegeAssertions(unittest.TestCase):
    def status(self):
        return "Uid:\t1000\t1000\t1000\t1000\nNoNewPrivs:\t1\n" + "".join(
            f"{name}:\t0000000000000000\n" for name in CAP_FIELDS)

    def test_application_has_no_capability_sets_and_nnp(self):
        self.assertEqual(process_privileges(self.status(), expected_uid=1000)["uid"], 1000)

    def test_every_capability_set_is_binding(self):
        for name in CAP_FIELDS:
            with self.subTest(name=name), self.assertRaises(AssertionError):
                process_privileges(self.status().replace(f"{name}:\t0000000000000000", f"{name}:\t0000000000000001"))

    def test_no_new_privileges_and_all_uid_slots_are_binding(self):
        for old, new in (("NoNewPrivs:\t1", "NoNewPrivs:\t0"), ("1000\t1000\t1000\t1000", "1000\t1000\t0\t1000")):
            with self.assertRaises(AssertionError):
                process_privileges(self.status().replace(old, new))
        with self.assertRaises(AssertionError):
            process_privileges(self.status(), expected_uid=1501)

    def test_missing_security_fields_cannot_pass(self):
        for name in (*CAP_FIELDS, "NoNewPrivs", "Uid"):
            status = "\n".join(line for line in self.status().splitlines() if not line.startswith(name+":"))
            with self.subTest(name=name), self.assertRaises(KeyError):
                process_privileges(status)

    def config(self):
        return {"services": {name: {"cap_drop": ["ALL"], "cap_add": sorted(caps),
                "security_opt": ["no-new-privileges:true"]} for name, caps in (("api", CAPABILITIES), ("web", set()))}}

    def test_canonical_policy_accepts_compose_normalized_spelling(self):
        config = self.config()
        self.assertTrue(compose_privileges(config))
        config["services"]["api"]["security_opt"] = ["no-new-privileges=true"]
        self.assertTrue(compose_privileges(config))

    def test_weakened_service_policy_is_rejected(self):
        for name in ("api", "web"):
            for key, value in (("cap_drop", []), ("cap_add", ["SYS_ADMIN"]),
                               ("security_opt", []), ("privileged", True)):
                config = copy.deepcopy(self.config())
                config["services"][name][key] = value
                with self.subTest(service=name, key=key), self.assertRaises(AssertionError):
                    compose_privileges(config)


if __name__ == "__main__":
    unittest.main()
