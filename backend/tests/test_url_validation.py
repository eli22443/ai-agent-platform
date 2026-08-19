import socket

import pytest

from app.repositories.errors import InvalidRepositoryUrl
from app.repositories.url_validation import validate_clone_url

ALLOWED_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")
PUBLIC_A_RECORD = "1.1.1.1"


def _public_getaddrinfo(host: str, port: int, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_A_RECORD, port))]


def _private_getaddrinfo(host: str, port: int, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", port))]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ssh://git@github.com/org/repo.git",
        "git@github.com:org/repo.git",
        "http://github.com/org/repo",
        "https://localhost/org/repo",
        "https://127.0.0.1/org/repo",
        "https://10.0.0.1/org/repo",
        "https://169.254.169.254/latest/meta-data",
        "https://evil.example/org/repo",
    ],
)
def test_validate_clone_url_rejects_disallowed_urls(url: str):
    with pytest.raises(InvalidRepositoryUrl):
        validate_clone_url(url, allowed_hosts=ALLOWED_HOSTS)


def test_userinfo_in_url_rejected():
    with pytest.raises(InvalidRepositoryUrl):
        validate_clone_url(
            "https://user:pass@github.com/org/repo",
            allowed_hosts=ALLOWED_HOSTS,
        )


def test_allow_listed_host_resolving_to_private_address_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("socket.getaddrinfo", _private_getaddrinfo)

    with pytest.raises(InvalidRepositoryUrl):
        validate_clone_url(
            "https://github.com/org/repo",
            allowed_hosts=ALLOWED_HOSTS,
        )


def test_github_https_url_allowed_with_public_dns(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("socket.getaddrinfo", _public_getaddrinfo)

    validate_clone_url(
        "https://github.com/psf/requests",
        allowed_hosts=ALLOWED_HOSTS,
    )
