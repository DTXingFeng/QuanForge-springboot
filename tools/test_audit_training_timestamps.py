"""Exercise the real SQLite load path without fitting models or loading sklearn."""
import importlib.util
import pathlib
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class StopAfterLoad(Exception):
    pass


class TrainingTimestampTests(unittest.TestCase):
    def test_training_and_inference_share_epoch_millisecond_minutes(self):
        with tempfile.TemporaryDirectory() as root:
            db = pathlib.Path(root) / "fixture.db"
            con = sqlite3.connect(db)
            con.execute("create table kline_1m(symbol text, open_time integer, open real, high real, low real, close real, volume real)")
            start = 1785601920000
            con.executemany("insert into kline_1m values('BTCUSDT',?,100,101,99,100,1)",
                            [(start + i * 60000,) for i in range(3000)])
            con.commit()
            con.close()
            # Training is never reached; optional heavy ML packages are deliberately absent.
            stubs = {name: types.ModuleType(name) for name in
                     ("sklearn", "sklearn.metrics", "sklearn.preprocessing", "sklearn.linear_model")}
            for name, fields in {"sklearn.metrics": ("accuracy_score", "classification_report"),
                                 "sklearn.preprocessing": ("StandardScaler",),
                                 "sklearn.linear_model": ("LogisticRegression",)}.items():
                for field in fields:
                    setattr(stubs[name], field, lambda *a, **kw: None)
            with patch.dict(sys.modules, stubs):
                for filename, builder in (("train_lgbm.py", "build"), ("train_baseline.py", "build_features")):
                    with self.subTest(filename=filename):
                        path = pathlib.Path(__file__).with_name(filename)
                        spec = importlib.util.spec_from_file_location("audit_training_module", path)
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        def inspect(df):
                            self.assertEqual(df.index[1] - df.index[0], module.pd.Timedelta(minutes=1))
                            self.assertEqual(df.index[0].year, 2026)
                            self.assertEqual(df.index[0].hour, 16)  # model_server uses UTC ms conversion
                            raise StopAfterLoad()
                        connections = []
                        real_connect = sqlite3.connect
                        def connect(*args, **kwargs):
                            connection = real_connect(*args, **kwargs)
                            connections.append(connection)
                            return connection
                        try:
                            with patch.object(module, builder, side_effect=inspect), patch.object(sys, "argv", [filename, "--db", str(db)]), patch.object(module.sqlite3, "connect", side_effect=connect):
                                with self.assertRaises(StopAfterLoad):
                                    module.main()
                        finally:
                            for connection in connections:
                                connection.close()


if __name__ == "__main__":
    unittest.main()
