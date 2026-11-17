"""Slack notifications: incoming-webhook style, bot-token style, or stdout when unconfigured."""

import pytest

from app.lib import config, log


@pytest.fixture
def slack_config(monkeypatch):
    def configure(url=None, token=None, channel=None):
        monkeypatch.setattr(config.messaging, "slack_url", url)
        monkeypatch.setattr(config.messaging, "slack_token", token)
        monkeypatch.setattr(config.messaging, "slack_channel", channel)

    return configure


async def test_slack_posts_to_incoming_webhook(http, slack_config):
    # The webhook wins when both styles are configured.
    slack_config(url="https://hooks.slack.invalid/T000/B000", token="xoxb-test", channel="#asfinfra")
    await log.slack("space archived")
    assert http.posts == [("https://hooks.slack.invalid/T000/B000", {"json": {"text": "space archived"}})]


async def test_slack_posts_with_token_to_channel(http, slack_config):
    slack_config(token="xoxb-test", channel="#asfinfra")
    await log.slack("space archived")
    ((url, kwargs),) = http.posts
    assert url == "https://slack.com/api/chat.postMessage"
    assert kwargs["headers"] == {"Authorization": "Bearer xoxb-test"}
    assert kwargs["json"] == {"channel": "#asfinfra", "text": "space archived"}


@pytest.mark.parametrize("partial", [{}, {"token": "xoxb-test"}, {"channel": "#asfinfra"}])
async def test_slack_prints_when_not_fully_configured(http, slack_config, capsys, partial):
    slack_config(**partial)
    await log.slack("space archived")
    assert not http.posts
    assert "space archived" in capsys.readouterr().out
