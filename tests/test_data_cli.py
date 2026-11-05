import json
from pathlib import Path
from typing import Any

import ccxt
import pytest
import yaml
from conftest import HOUR_MS, T0, FakeExchange, bar, hourly

import sentinel_quant.data.client as client_module
from sentinel_quant.cli import main
from sentinel_quant.data.store import PARQUET_NAME, DatasetKey, DatasetStore

ROOT = Path(__file__).resolve().parents[1]
NOW = T0 + 6 * HOUR_MS + 5000


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "data_dir": str(tmp_path / "data"),
                "exchange": {"symbols": ["BTC/USDT"], "timeframe": "1h"},
                "data": {"history_start": "2023-11-14", "page_limit": 3},
            }
        ),
        encoding="utf-8",
    )
    return path


def use_exchange(monkeypatch: pytest.MonkeyPatch, exchange: Any) -> None:
    monkeypatch.setattr(client_module, "build_public_exchange", lambda _name: exchange)


def latest_id(tmp_path: Path) -> str:
    manifest = DatasetStore(tmp_path / "data").latest(DatasetKey("binance", "BTC/USDT", "1h"))
    assert manifest is not None
    return manifest.dataset_id


def test_download_then_report(
    tmp_path: Path,
    config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_exchange(monkeypatch, FakeExchange(NOW, hourly(T0, 6)))
    assert main(["data", "download", "--config", str(config)]) == 0
    capsys.readouterr()
    assert main(["data", "report", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert latest_id(tmp_path) in out


def test_download_rerun_is_idempotent(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_exchange(monkeypatch, FakeExchange(NOW, hourly(T0, 6)))
    assert main(["data", "download", "--config", str(config)]) == 0
    first = latest_id(tmp_path)
    assert main(["data", "download", "--config", str(config)]) == 0
    assert latest_id(tmp_path) == first


def test_report_json_and_explicit_id(
    tmp_path: Path,
    config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_exchange(monkeypatch, FakeExchange(NOW, hourly(T0, 6)))
    main(["data", "download", "--config", str(config)])
    capsys.readouterr()
    dataset_id = latest_id(tmp_path)
    args = ["data", "report", "--config", str(config), "--dataset-id", dataset_id, "--json"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_report_needs_no_network_and_strict_fails_on_warnings(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_exchange(monkeypatch, FakeExchange(NOW, hourly(T0, 2) + hourly(T0 + 4 * HOUR_MS, 2)))
    main(["data", "download", "--config", str(config)])

    def no_client(_name: str) -> None:
        raise AssertionError("report must not build a client")

    monkeypatch.setattr(client_module, "build_public_exchange", no_client)
    assert main(["data", "report", "--config", str(config)]) == 0
    assert main(["data", "report", "--config", str(config), "--strict"]) == 1


def test_bad_data_fails_download_and_report(config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_exchange(monkeypatch, FakeExchange(NOW, [bar(T0, price=-1.0)]))
    assert main(["data", "download", "--config", str(config)]) == 1
    assert main(["data", "report", "--config", str(config)]) == 1


def test_report_detects_corruption(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_exchange(monkeypatch, FakeExchange(NOW, hourly(T0, 6)))
    main(["data", "download", "--config", str(config)])
    dataset_id = latest_id(tmp_path)
    parquet = tmp_path / "data/ohlcv/binance/spot/BTC-USDT/1h" / dataset_id / PARQUET_NAME
    parquet.write_bytes(parquet.read_bytes()[:-10])
    assert main(["data", "report", "--config", str(config)]) == 1


def test_report_without_data_fails(config: Path) -> None:
    assert main(["data", "report", "--config", str(config)]) == 1


def test_exchange_failure_is_a_clean_error(config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exchange = FakeExchange(NOW, hourly(T0, 6))
    exchange.errors = [ccxt.BadSymbol("rejected")]
    use_exchange(monkeypatch, exchange)
    assert main(["data", "download", "--config", str(config)]) == 1


def test_since_and_until_bound_the_download(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_exchange(monkeypatch, FakeExchange(T0 + 100 * HOUR_MS, hourly(T0, 100)))
    args = ["data", "download", "--config", str(config)]
    assert main([*args, "--since", "2023-11-15", "--until", "2023-11-16"]) == 0
    frame = DatasetStore(tmp_path / "data").load(latest_id(tmp_path))
    assert frame.height == 24
    assert str(frame["timestamp"][0]).startswith("2023-11-15 00:00:00")


def test_invalid_config_fails(tmp_path: Path) -> None:
    assert main(["data", "report", "--config", str(tmp_path / "missing.yaml")]) == 1


def test_data_package_is_not_git_ignored() -> None:
    # An unanchored `data/` pattern also matches sentinel_quant/data/, dropping the
    # package from commits and from the built wheel.
    patterns = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/data/" in patterns
    assert "data/" not in patterns
