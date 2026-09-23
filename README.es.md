# Codex Run Budget

**Límites orientativos de tokens compartidos y visibilidad local del uso para las Tasks de Codex y sus subagentes.**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português](README.pt.md)

Codex Run Budget es un plugin local de Codex que permite compartir un presupuesto entre una Task principal y sus subagentes. También ofrece registros automáticos por turno, informes de Tasks con alcance definido, observaciones de la cuota nativa de la cuenta y vistas opcionales de la actividad de flujos de trabajo y `codex exec`. Las decisiones del presupuesto siguen reglas deterministas en Python y SQLite. Consultar un informe no inicia un presupuesto.

## Funciones

- **Presupuesto compartido:** la `session_id` de la Task principal identifica toda la ejecución. STEER y HALT se aplican en los límites de hooks compatibles.
- **Registros e informes:** consulta tarjetas automáticas por turno y observaciones de una Task, un árbol de agentes o un período elegido explícitamente. La información sin pruebas suficientes sigue marcada como parcial o desconocida.
- **Cuota y actividad:** lee la cuota nativa de la cuenta Codex y, cuando se solicita, observa flujos de trabajo o actividad de `codex exec` de un proyecto. Los porcentajes de la cuenta no son cargos de una Task.
- **Local y privado:** el registro guarda solo contadores, estados, marcas de tiempo e identificadores cifrados mediante hash permitidos. No guarda deliberadamente prompts, comandos ni contenido de herramientas. Solo requiere Python 3.10+ y su biblioteca estándar en tiempo de ejecución.

## Inicio rápido

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

En la CLI de Codex, revisa y confía en los hooks del plugin desde `/hooks`; después inicia una **Task nueva**. Coloca esta línea al principio del mensaje:

```text
run-budget:start tokens=100k

Implement the feature and run the relevant checks.
```

`run-budget:status` muestra el estado; `run-budget:halt reason="operator pause"`, `run-budget:resume tokens=200k` y `run-budget:off` controlan el presupuesto. [Todos los comandos y ejemplos](README.md#commands-by-task) · [Diseño y reglas](docs/DESIGN.md).

## Límites

Codex no ofrece un hook antes de cada petición al modelo; las herramientas alojadas pueden omitir los hooks locales. Los contadores pueden llegar después de una acción, por lo que un turno puede superar el presupuesto antes de observar HALT. Son límites orientativos, sin garantía de facturación exacta, exceso cero o aplicación universal. [Validación y límites](docs/VALIDATION.md).

[README completo en inglés](README.md) · [Índice de documentación](docs/README.md) · [Idiomas](docs/LOCALIZATION.md) · [Seguridad](SECURITY.md)

Proyecto comunitario independiente; no es un producto de OpenAI ni de Microsoft. MIT © EasyVibeCoding contributors.
