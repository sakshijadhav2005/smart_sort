"""Posts quarantined/failed files and health alerts to a Slack webhook.

Config::

    plugins:
      builtin: [slack_alert]
      settings:
        slack_alert:
          webhook_url: https://hooks.slack.com/services/...   # or SORTSMART_SLACK_WEBHOOK
          events: [quarantined, failed]
"""
import json
import logging
import os
import urllib.request

from sortsmart.plugins import Action

log = logging.getLogger("sortsmart.plugins.slack")


class SlackAlert(Action):
    name = "slack_alert"
    events = ("quarantined", "failed")

    def setup(self, settings):
        self.webhook = settings.get("webhook_url") or os.environ.get("SORTSMART_SLACK_WEBHOOK")
        self.timeout = float(settings.get("timeout", 5))
        if settings.get("events"):
            self.events = tuple(settings["events"])
        if not self.webhook:
            log.warning("slack_alert has no webhook_url; alerts are not sent")

    def run(self, result, file):
        self._post(f":warning: SortSmart {result.status} `{file.name}`: "
                   f"{result.reason or result.destination}")

    def alert(self, message, details):
        self._post(f":rotating_light: SortSmart health: {message}")

    def _post(self, text):
        if not self.webhook:
            return
        req = urllib.request.Request(self.webhook, data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout):
            pass
