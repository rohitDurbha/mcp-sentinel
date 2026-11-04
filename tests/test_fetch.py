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
