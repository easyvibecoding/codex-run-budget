# Codex Run Budget

**Des garde-fous de jetons partagés et une visibilité locale sur l'utilisation des Tasks Codex et de leurs sous-agents.**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português](README.pt.md)

Codex Run Budget est un plugin Codex local qui permet à une Task parente et à ses sous-agents de partager un seul budget. Il fournit aussi des relevés automatiques par tour, des rapports de Tasks à portée définie, des observations du quota natif du compte et, en option, des vues des activités de workflow et de `codex exec`. Les décisions budgétaires suivent des règles déterministes en Python et SQLite. Consulter un rapport ne démarre pas de budget.

## Fonctionnalités

- **Budget partagé :** la `session_id` de la Task parente identifie toute l'exécution. STEER et HALT s'appliquent aux points de passage des hooks pris en charge.
- **Relevés et rapports :** consultez les cartes automatiques par tour et les observations d'une Task, d'un arbre d'agents ou d'une période explicitement choisie. Les données manquantes restent indiquées comme partielles ou inconnues.
- **Quota et activité :** lisez le quota natif du compte Codex et observez au besoin les workflows ou l'activité `codex exec` d'un projet. Les pourcentages du compte ne représentent pas le coût d'une Task.
- **Local et privé :** le registre ne conserve que les compteurs, états, horodatages et identifiants hachés autorisés. Il n'enregistre pas volontairement les prompts, commandes ou contenus des outils. Python 3.10+ et sa bibliothèque standard suffisent à l'exécution.

## Démarrage rapide

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

Dans la CLI Codex, vérifiez et approuvez les hooks du plugin dans `/hooks`, puis créez une **nouvelle Task**. Placez cette ligne au début de son message :

```text
run-budget:start tokens=100k

Implement the feature and run the relevant checks.
```

`run-budget:status` affiche l'état ; `run-budget:halt reason="operator pause"`, `run-budget:resume tokens=200k` et `run-budget:off` pilotent le budget. [Toutes les commandes et exemples](README.md#commands-by-task) · [Conception et règles](docs/DESIGN.md).

## Limites d'application

Codex ne fournit pas de hook de plugin avant chaque requête au modèle ; les outils hébergés peuvent contourner les hooks locaux. Les compteurs de jetons peuvent arriver après une action : un tour peut donc dépasser le budget avant l'observation de HALT. Ce sont des garde-fous, sans garantie de facturation exacte, de dépassement nul ou d'application universelle. [Validation et limites](docs/VALIDATION.md).

[README anglais détaillé](README.md) · [Index de la documentation](docs/README.md) · [Langues](docs/LOCALIZATION.md) · [Sécurité](SECURITY.md)

Projet communautaire indépendant, sans affiliation produit avec OpenAI ou Microsoft. MIT © EasyVibeCoding contributors.
