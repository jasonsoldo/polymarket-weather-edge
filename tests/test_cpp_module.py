import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class CppModuleTests(unittest.TestCase):
    def test_cpp_pnl_curve_engine_source_exists(self):
        source = Path("cpp/pnl_curve_engine/pnl_curve_engine.cpp")
        self.assertTrue(source.exists())
        self.assertIn("pnl_if_wins", source.read_text(encoding="utf-8"))

    def test_cpp_pnl_curve_engine_compiles_when_gpp_is_available(self):
        compiler = shutil.which("g++")
        if not compiler:
            self.skipTest("g++ is not installed")

        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "pnl_curve_engine"
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "cpp/pnl_curve_engine/pnl_curve_engine.cpp",
                    "-o",
                    str(exe),
                ],
                check=True,
            )
            result = subprocess.run(
                [str(exe), "data/sample_buckets.csv"],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("bucket,price,shares,cost,model_probability,edge,pnl_if_wins", result.stdout)
        self.assertIn("88F,0.300000,2.000000,0.600000,0.380000,0.080000,0.690000", result.stdout)
