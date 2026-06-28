"""Time-based automations.

A thin layer over APScheduler that fires scenes on cron-style schedules. Rules
are plain dicts (easy to load from YAML/JSON), so the API and config file share
the same shape:

    {
      "name": "wake up",
      "did": "abcdef...",          # device id
      "scene": "sunrise",          # registered scene name
      "params": {"seconds": 1200}, # scene options
      "cron": {"hour": 6, "minute": 30, "day_of_week": "mon-fri"}
    }

You can also use ``"at": "06:30"`` as a shortcut for a daily cron.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .effects import SceneRunner


@dataclass
class Rule:
    name: str
    did: str
    scene: str
    params: dict = field(default_factory=dict)
    cron: dict = field(default_factory=dict)
    at: str | None = None
    enabled: bool = True

    def trigger(self) -> CronTrigger:
        if self.at:
            hh, mm = self.at.split(":")
            return CronTrigger(hour=int(hh), minute=int(mm))
        return CronTrigger(**self.cron)


class Automations:
    def __init__(self, runner: SceneRunner):
        self.runner = runner
        self.sched = AsyncIOScheduler()
        self.rules: dict[str, Rule] = {}

    def start(self) -> None:
        if not self.sched.running:
            self.sched.start()

    def shutdown(self) -> None:
        if self.sched.running:
            self.sched.shutdown(wait=False)

    def add(self, rule: Rule) -> None:
        self.remove(rule.name)
        self.rules[rule.name] = rule
        if rule.enabled:
            self.sched.add_job(
                self._fire, trigger=rule.trigger(), id=rule.name,
                args=[rule.name], replace_existing=True,
            )

    def remove(self, name: str) -> None:
        self.rules.pop(name, None)
        if self.sched.get_job(name):
            self.sched.remove_job(name)

    def list(self) -> list[Rule]:
        return list(self.rules.values())

    async def _fire(self, name: str) -> None:
        rule = self.rules.get(name)
        if rule and rule.enabled:
            await self.runner.start(rule.did, rule.scene, **rule.params)

    def load(self, rules: list[dict]) -> None:
        for r in rules:
            self.add(Rule(**r))
