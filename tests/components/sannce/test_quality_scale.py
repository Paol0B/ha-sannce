from pathlib import Path
from typing import Any

import yaml

import custom_components.sannce as integration

RULES: dict[str, Any] = yaml.safe_load(
    (Path(integration.__file__).parent / "quality_scale.yaml").read_text()
)["rules"]
# ALL_RULES of script/hassfest/quality_scale.py in Home Assistant 2026.10, in order
ALL_RULES = (
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow",
    "config-flow-test-coverage",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "docs-triggers",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
    "devices",
    "diagnostics",
    "discovery",
    "discovery-update-info",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
    "async-dependency",
    "inject-websession",
    "strict-typing",
)
EXEMPT = {
    "action-setup",
    "docs-actions",
    "docs-conditions",
    "docs-triggers",
    "docs-configuration-parameters",
    "dynamic-devices",
    "stale-devices",
    "repair-issues",
}
PUBLICATION = {"brands", "dependency-transparency"}


def status(rule: str) -> str:
    value = RULES[rule]
    return value if isinstance(value, str) else value["status"]


def test_every_rule_is_listed_once_in_hassfest_order() -> None:
    assert len(ALL_RULES) == 54
    assert list(RULES) == list(ALL_RULES)


def test_only_publication_rules_are_todo() -> None:
    assert {rule for rule in RULES if status(rule) == "todo"} == PUBLICATION
    assert {rule for rule in RULES if status(rule) == "exempt"} == EXEMPT


def test_every_rule_not_done_says_why() -> None:
    for rule in RULES:
        if status(rule) != "done":
            assert RULES[rule]["comment"].strip(), rule
