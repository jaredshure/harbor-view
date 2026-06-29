"""Tests for harbor_view.appliance.provider_selection."""
from __future__ import annotations

from harbor_view.appliance.provider_selection import get_configured_provider
from harbor_view.providers import AISProvider, PlaceholderProvider


def test_defaults_to_placeholder_when_unset(monkeypatch):
    monkeypatch.delenv("HARBOR_VIEW_PROVIDER", raising=False)
    provider = get_configured_provider()
    assert isinstance(provider, PlaceholderProvider)


def test_explicit_placeholder(monkeypatch):
    monkeypatch.setenv("HARBOR_VIEW_PROVIDER", "placeholder")
    assert isinstance(get_configured_provider(), PlaceholderProvider)


def test_explicit_ais(monkeypatch):
    monkeypatch.setenv("HARBOR_VIEW_PROVIDER", "ais")
    assert isinstance(get_configured_provider(), AISProvider)


def test_case_insensitive(monkeypatch):
    monkeypatch.setenv("HARBOR_VIEW_PROVIDER", "AIS")
    assert isinstance(get_configured_provider(), AISProvider)


def test_unrecognized_value_falls_back_to_placeholder(monkeypatch):
    monkeypatch.setenv("HARBOR_VIEW_PROVIDER", "definitely-not-a-real-provider")
    provider = get_configured_provider()
    assert isinstance(provider, PlaceholderProvider)
