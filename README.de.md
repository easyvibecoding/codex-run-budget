# Codex Run Budget

**Gemeinsame Token-Leitplanken und lokale Nutzungsübersicht für Codex Tasks und Subagenten.**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português](README.pt.md)

Codex Run Budget ist ein lokales Codex-Plugin, mit dem ein übergeordneter Task und seine Subagenten ein einziges Budget teilen. Es bietet außerdem automatische Nutzungsbelege pro Turn, Task-Berichte mit festgelegtem Umfang, Beobachtungen des nativen Kontokontingents sowie optionale Ansichten für Workflow- und `codex exec`-Aktivitäten. Budgetentscheidungen folgen deterministischen Regeln in Python und SQLite. Das Lesen eines Berichts aktiviert kein Budget.

## Funktionen

- **Gemeinsames Budget:** Die `session_id` des übergeordneten Tasks ist der Schlüssel für den gesamten Lauf. STEER und HALT greifen an unterstützten Hook-Grenzen.
- **Belege und Berichte:** Automatische Turn-Karten sowie Beobachtungen für einen Task, einen Agentenbaum oder einen ausdrücklich gewählten Zeitraum. Fehlende Nachweise bleiben als teilweise oder unbekannt gekennzeichnet.
- **Kontingent und Aktivitäten:** Liest das native Codex-Kontokontingent und beobachtet bei Bedarf Workflows oder projektbezogene `codex exec`-Aktivitäten. Kontoprozente sind keine Task-Kosten.
- **Lokal und privat:** Das Ledger speichert nur zugelassene Zähler, Zustände, Zeitpunkte und gehashte Kennungen. Prompts, Befehle und Tool-Inhalte werden nicht absichtlich gespeichert. Zur Laufzeit reichen Python 3.10+ und die Standardbibliothek.

## Schnellstart

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

Prüfe und vertraue den Plugin-Hooks unter `/hooks` in der Codex CLI. Starte danach einen **neuen Task** und setze diese Zeile an den Anfang der Task-Nachricht:

```text
run-budget:start tokens=100k

Implement the feature and run the relevant checks.
```

`run-budget:status` zeigt den Zustand. Mit `run-budget:halt reason="operator pause"`, `run-budget:resume tokens=200k` und `run-budget:off` steuerst du das Budget. [Alle Befehle und Beispiele](README.md#commands-by-task) · [Entwurf und Regeln](docs/DESIGN.md).

## Grenzen

Codex bietet keinen Plugin-Hook vor jeder Modellanfrage; Hosted Tools können lokale Tool-Hooks umgehen. Token-Zähler können erst nach einer Aktion eintreffen, sodass ein Turn das Budget überschreiten kann, bevor HALT beobachtet wird. Das Plugin bietet Leitplanken, aber keine exakte Abrechnung, Garantie gegen Überschreitungen oder universelle Durchsetzung. [Validierung und Grenzen](docs/VALIDATION.md).

[Ausführliche englische README](README.md) · [Dokumentation](docs/README.md) · [Sprachen](docs/LOCALIZATION.md) · [Sicherheit](SECURITY.md)

Unabhängiges Community-Projekt; kein Produkt von OpenAI oder Microsoft. MIT © EasyVibeCoding contributors.
