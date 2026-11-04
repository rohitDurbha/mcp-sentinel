import pytest

from mcp_watcher.fetch import normalize_repo_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://github.com/acme/weather", ("https://github.com/acme/weather", None)),
        ("https://github.com/acme/weather.git", ("https://github.com/acme/weather", None)),
        ("https://github.com/Acme/Weather/", ("https://github.com/acme/weather", None)),
        (
            "https://github.com/acme/mono/tree/main/servers/a",
            ("https://github.com/acme/mono", "servers/a"),
        ),
        ("http://github.com/acme/weather", ("https://github.com/acme/weather", None)),
        ("https://gitlab.com/group/sub/proj", ("https://gitlab.com/group/sub/proj", None)),
    ],
)
def test_normalize_accepts_known_hosts(raw, expected):
    assert normalize_repo_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "file:///etc/passwd",
        "git@github.com:acme/weather.git",
        "https://evil.example.com/acme/weather",
        "https://github.com/acme",
        "https://github.com/acme/weather/tree/main/../../etc",
        "",
    ],
)
def test_normalize_rejects_unsafe_or_unknown(raw):
    assert normalize_repo_url(raw) is None


def _clean_git_env(monkeypatch):
    import os

    for key in [k for k in os.environ if k.startswith("GIT_CONFIG_")]:
        monkeypatch.delenv(key)


class _Ran:
    def __init__(self, stdout="a" * 40 + "\tHEAD\n"):
        self.calls = []
        self.stdout = stdout

    def __call__(self, argv, **kwargs):
        import subprocess

        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=self.stdout, stderr="")


def test_commit_check_uses_a_short_timeout(monkeypatch):
    from mcp_watcher import fetch

    ran = _Ran()
    monkeypatch.setattr(fetch.subprocess, "run", ran)
    assert fetch.remote_head("https://github.com/acme/weather") == "a" * 40
    assert ran.calls[0][1]["timeout"] == fetch.LS_REMOTE_TIMEOUT < fetch.CLONE_TIMEOUT


def test_github_token_is_sent_only_to_github_and_never_on_the_command_line(monkeypatch):
    import base64

    from mcp_watcher import fetch

    ran = _Ran()
    _clean_git_env(monkeypatch)
    monkeypatch.setattr(fetch.subprocess, "run", ran)
    monkeypatch.setenv("MCP_WATCHER_GITHUB_TOKEN", "tok123")
    fetch.remote_head("https://github.com/acme/weather")
    argv, kwargs = ran.calls[0]
    env = kwargs["env"]
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    expected = base64.b64encode(b"x-access-token:tok123").decode()
    assert env["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: basic {expected}"
    assert "MCP_WATCHER_GITHUB_TOKEN" not in env
    assert not any("tok123" in a or expected in a for a in argv)


def test_no_token_means_no_auth_header(monkeypatch):
    from mcp_watcher import fetch

    ran = _Ran()
    _clean_git_env(monkeypatch)
    monkeypatch.setattr(fetch.subprocess, "run", ran)
    monkeypatch.delenv("MCP_WATCHER_GITHUB_TOKEN", raising=False)
    fetch.remote_head("https://github.com/acme/weather")
    env = ran.calls[0][1]["env"]
    assert "GIT_CONFIG_COUNT" not in env
    assert not any(k.startswith("GIT_CONFIG_KEY") for k in env)


def test_token_entry_is_appended_after_existing_git_config_entries(monkeypatch):
    from mcp_watcher import fetch

    ran = _Ran()
    _clean_git_env(monkeypatch)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.interactive")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "never")
    monkeypatch.setattr(fetch.subprocess, "run", ran)
    monkeypatch.setenv("MCP_WATCHER_GITHUB_TOKEN", "tok123")
    fetch.remote_head("https://github.com/acme/weather")
    env = ran.calls[0][1]["env"]
    assert env["GIT_CONFIG_COUNT"] == "2"
    kept = (env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"])
    assert kept == ("credential.interactive", "never")
    assert env["GIT_CONFIG_KEY_1"] == "http.https://github.com/.extraheader"
