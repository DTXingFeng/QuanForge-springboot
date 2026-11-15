"""Apply the small safety patch to a private deployment copy, then block all IO.

Usage: python tools/tests/test_deployed_v5_safety.py --source <snapshot>/tools/paper_v5mech.py
The source is never changed. No credentials are copied into the test directory.
"""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    with tempfile.TemporaryDirectory(prefix="qfs-v5-safety-") as d:
        work = Path(d)
        (work / "tools").mkdir()
        destination = work / "tools/paper_v5mech.py"
        destination.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        local_patch = work / "safety.patch"
        local_patch.write_bytes((ROOT / "docs/audit-20261112/deployed-v5-safety.patch").read_bytes().replace(b"\r\n", b"\n"))
        subprocess.run(["git", "apply", "--unsafe-paths", "--directory=" + work.as_posix(),
                        str(local_patch)], check=True)
        spec = importlib.util.spec_from_file_location("deployed_v5_safe", destination)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.DEMO = {"api_key": "fake", "api_secret": "fake", "base": "https://api.bybit.com"}
        with patch.object(module.opener_px, "open", side_effect=AssertionError("network forbidden")) as px, \
                patch.object(module.opener_direct, "open", side_effect=AssertionError("network forbidden")) as direct:
            for method in ("GET", "POST"):
                try:
                    module.demo_call(method, "/v5/order/create", body={})
                except RuntimeError as error:
                    assert "audit safety lock" in str(error)
                else:
                    raise AssertionError("shadow call was not blocked")
            module.demo_open("ACEUSDT", "BUY", 100., 200.)
            module.demo_close_sym("ACEUSDT")
            module.reconcile()
            module.demo_balance()
            assert px.call_count == 0 and direct.call_count == 0
        print("PASS: patch applied to private copy; all shadow entry points blocked; network calls=0")


if __name__ == "__main__":
    main()
