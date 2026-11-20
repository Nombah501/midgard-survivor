"""First install and uninstall through the setup seam, without the real game or scheduler."""

import stat
import sys
from pathlib import Path

import pytest

from midgard_farm import assets, platform, setup
from midgard_farm.core.install import current_service, launch_current
from midgard_farm.core.patch_info import INSTALLED_PACK
from test_profile import make_profile


class FakeInstallPlatform(type(platform.current())):
    def __init__(self, home: Path):
        self.home = home
        self.registration = None
        self.calls = []
        self.running = False
        self.launched = []

    def app_data_dir(self):
        return self.home / "app data"

    def godot_user_data_root(self):
        return self.home / "fake game profiles"

    def render_service(self, argv):
        return f"Fake service command: {argv[0]}\n"

    def register_service(self, argv):
        self.calls.append("register")
        self.registration = argv

    def unregister_service(self):
        self.calls.append("unregister")
        self.registration = None

    def setup_warnings(self):
        return ("fake platform warning",)

    def game_running(self):
        return self.running

    def run_service_binary(self, argv):
        self.launched.append(argv)
        return 0


@pytest.fixture
def fake(tmp_path, monkeypatch):
    os_ = FakeInstallPlatform(tmp_path)
    monkeypatch.setattr(platform, "current", lambda: os_)
    return os_

@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "unpacked archive" / "midgard-farm"
    (root / "_internal").mkdir(parents=True)
    (root / "_internal" / "data").write_bytes(b"bundled payload")
    suffix = ".exe" if sys.platform == "win32" else ""
    launcher = root / "launcher"
    (launcher / "_internal").mkdir(parents=True)
    (launcher / "_internal" / "data").write_bytes(b"launcher runtime")
    for name in ("midgard-farm", "midgard-farm-service", "midgard-farm-setup", "launcher/midgard-farm-launcher"):
        file = root / f"{name}{suffix}"
        file.write_bytes(b"bundled executable")
        file.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(root / f"midgard-farm-setup{suffix}"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(assets, "version", lambda: "2.1.0")
    return root


def test_setup_selects_the_version_stores_the_token_privately_and_can_be_rerun(fake, bundle, monkeypatch, capsys):
    secret = "fixture-read-only-secret"
    prompts = []

    def enter_token(prompt):
        prompts.append(prompt)
        return secret

    monkeypatch.setattr(setup, "getpass", enter_token)
    assert setup.main([]) == 0
    data = fake.app_data_dir()
    installed = data / "versions" / "2.1.0"
    suffix = Path(sys.executable).suffix
    assert (data / "current").read_text(encoding="utf-8") == "2.1.0\n"
    assert (installed / "_internal" / "data").read_bytes() == b"bundled payload"
    assert (installed / f"midgard-farm{suffix}").is_file()
    assert (installed / f"midgard-farm-setup{suffix}").is_file()
    launcher = data / "bin" / f"midgard-farm-launcher{suffix}"
    assert fake.registration == [str(launcher)]
    assert launcher.read_bytes() == b"bundled executable"
    assert (launcher.parent / "_internal" / "data").read_bytes() == b"launcher runtime"
    assert current_service(fake) == installed / f"midgard-farm-service{suffix}"
    output = capsys.readouterr()
    assert "fake platform warning" in output.err
    assert secret not in output.out + output.err
    token = data / "release-token"
    assert token.read_text(encoding="utf-8") == secret + "\n"
    assert not (bundle / "release-token").exists()
    assert not (data / "logs").exists()
    if sys.platform == "linux":
        assert stat.S_IMODE(token.stat().st_mode) == 0o600
        assert stat.S_IMODE(current_service(fake).stat().st_mode) == 0o755
    copied_at = (installed / "_internal" / "data").stat().st_mtime_ns
    token_at = token.stat().st_mtime_ns
    for executable in (sys.executable, installed / Path(sys.executable).name):
        monkeypatch.setattr(sys, "executable", str(executable))
        assert setup.main([]) == 0
    assert len(prompts) == 1
    assert fake.registration == [str(launcher)]
    assert (installed / "_internal" / "data").stat().st_mtime_ns == copied_at
    assert token.stat().st_mtime_ns == token_at
    assert [p.name for p in (data / "versions").iterdir()] == ["2.1.0"]
    (launcher.parent / "_internal" / "data").write_bytes(b"old launcher runtime")
    assert setup.main([]) == 0
    assert (launcher.parent / "_internal" / "data").read_bytes() == b"launcher runtime"
    assert fake.registration == [str(launcher)]


def test_setup_repairs_an_empty_installed_version_before_selecting_it(fake, bundle, monkeypatch):
    monkeypatch.setattr(setup, "getpass", lambda _: "fixture-token")
    data = fake.app_data_dir()
    target = data / "versions" / "2.1.0"
    target.mkdir(parents=True)
    (data / "current").write_bytes(b"2.0.0\n")

    assert setup.main([]) == 0
    assert (data / "current").read_bytes() == b"2.1.0\n"
    assert current_service(fake).parent == target
    launcher = target / "launcher" / ("midgard-farm-launcher" + fake.executable_suffix)
    assert launcher.read_bytes() == b"bundled executable"


def test_cannot_select_an_incomplete_version_if_repair_fails(fake, bundle, monkeypatch, capsys):
    monkeypatch.setattr(setup, "getpass", lambda _: "fixture-token")
    data = fake.app_data_dir()
    target = data / "versions" / "2.1.0"
    target.mkdir(parents=True)
    pointer = data / "current"
    pointer.write_bytes(b"2.0.0\n")
    replace = fake.replace_atomic

    def fail_staged_swap(src, dst):
        if Path(src).name == "release" and Path(dst) == target:
            assert not target.exists()
            raise PermissionError("fake blocked version replacement")
        replace(src, dst)

    monkeypatch.setattr(fake, "replace_atomic", fail_staged_swap)
    assert setup.main([]) == 1
    assert "fake blocked version replacement" in capsys.readouterr().err
    assert pointer.read_bytes() == b"2.0.0\n"
    assert target.is_dir() and not list(target.iterdir())
    assert not fake.calls


def test_setup_prints_the_launcher_registration_without_installing(fake, capsys):
    launcher = fake.app_data_dir() / "bin" / ("midgard-farm-launcher" + fake.executable_suffix)
    assert setup.main(["--print-registration"]) == 0
    assert str(launcher) in capsys.readouterr().out
    assert not fake.app_data_dir().exists()
    assert not fake.calls


def test_current_pointer_changes_service_without_reregistering(fake, bundle, monkeypatch):
    monkeypatch.setattr(setup, "getpass", lambda _: "fixture-token")
    assert setup.main([]) == 0
    first_registration = fake.registration
    first = current_service(fake)
    second = first.parent.with_name("2.2.0") / first.name
    second.parent.mkdir()
    second.write_bytes(b"updated service")

    fake.write_atomic(fake.app_data_dir() / "current", b"2.2.0\n")
    assert launch_current(fake, ["--self-check", "some report.json"]) == 0
    fake.write_atomic(fake.app_data_dir() / "current", b"2.1.0\n")
    assert launch_current(fake, []) == 0
    assert fake.launched == [[str(second), "--self-check", "some report.json"], [str(first)]]
    assert fake.registration == first_registration
    assert fake.calls == ["register"]


@pytest.mark.parametrize("pointer", [None, b"../../moved\n", b"1..2\n", b"1.2.3\n"])
def test_launcher_refuses_missing_malformed_or_dangling_pointer(fake, pointer, capsys):
    data = fake.app_data_dir()
    data.mkdir()
    if pointer is not None:
        (data / "current").write_bytes(pointer)
    assert launch_current(fake, []) == 1
    assert "midgard-farm-launcher:" in (error := capsys.readouterr().err)
    assert "current release" in error
    assert not fake.launched


def mounted_profile(fake):
    profile = make_profile(fake.godot_user_data_root(), "Fixture Game")
    patches = profile / "patches"
    official = b'{"file":"official.pck","version":"1"}\n'
    (patches / "official.pck").write_bytes(b"official pack")
    (patches / "official-state.json").write_bytes(official)
    (patches / INSTALLED_PACK).write_bytes(b"farmer pack")
    (patches / "state.json").write_text(f'{{"file":"{INSTALLED_PACK}","farmer":1}}', encoding="utf-8")
    return profile, official


def test_uninstall_unregisters_and_restores_official_patch_without_removing_data(fake):
    profile, official = mounted_profile(fake)
    data = fake.app_data_dir()
    logs = data / "logs"
    logs.mkdir(parents=True)
    history = data / "history.jsonl"
    log = logs / "session.log"
    history.write_bytes(b"past nights")
    log.write_bytes(b"past logs")
    original = (profile / "profile.json").read_bytes()

    for _ in range(2):
        assert setup.main(["--uninstall"]) == 0
        assert (profile / "patches" / "state.json").read_bytes() == official
        assert not (profile / "patches" / INSTALLED_PACK).exists()
    assert fake.calls == ["unregister", "unregister"]
    assert (profile / "profile.json").read_bytes() == original
    assert history.read_bytes() == b"past nights"
    assert log.read_bytes() == b"past logs"


def test_uninstall_refuses_while_game_runs(fake, capsys):
    profile, _ = mounted_profile(fake)
    fake.running = True

    assert setup.main(["--uninstall"]) == 1
    assert "close it first" in capsys.readouterr().err
    assert (profile / "patches" / INSTALLED_PACK).exists()
    assert fake.calls == []


def test_uninstall_restores_a_profile_missing_its_current_state(fake):
    profile, official = mounted_profile(fake)
    patches = profile / "patches"
    (patches / "state.json").unlink()

    assert setup.main(["--uninstall"]) == 0
    assert fake.calls == ["unregister"]
    assert (patches / "state.json").read_bytes() == official
    assert not (patches / INSTALLED_PACK).exists()


def test_uninstall_does_not_restore_during_a_legacy_launch(fake, capsys):
    profile, official = mounted_profile(fake)
    patches = profile / "patches"
    with fake.acquire_lock(profile / "farmer.run.lock"):
        assert setup.main(["--uninstall"]) == 1
    assert "legacy" in capsys.readouterr().err
    assert (patches / "state.json").read_bytes() != official
    assert (patches / INSTALLED_PACK).exists()
