# Codex Run Budget

**Limites orientadores de tokens compartilhados e visibilidade local do uso para Tasks do Codex e seus subagentes.**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português](README.pt.md)

Codex Run Budget é um plugin local do Codex que permite compartilhar um único orçamento entre uma Task principal e seus subagentes. Ele também oferece registros automáticos por turno, relatórios de Tasks com escopo definido, observações da cota nativa da conta e visualizações opcionais de atividades de fluxo de trabalho e `codex exec`. As decisões de orçamento seguem regras determinísticas em Python e SQLite. Consultar um relatório não inicia um orçamento.

## Recursos

- **Orçamento compartilhado:** a `session_id` da Task principal identifica toda a execução. STEER e HALT são aplicados nos limites de hooks compatíveis.
- **Registros e relatórios:** consulte cartões automáticos por turno e observações de uma Task, de uma árvore de agentes ou de um período explicitamente escolhido. Dados sem evidência suficiente permanecem parciais ou desconhecidos.
- **Cota e atividade:** leia a cota nativa da conta Codex e observe, quando necessário, fluxos de trabalho ou atividades de `codex exec` de um projeto. Percentuais da conta não são custos de uma Task.
- **Local e privado:** o registro armazena apenas contadores, estados, horários e identificadores com hash permitidos. Não armazena intencionalmente prompts, comandos nem conteúdo de ferramentas. Para execução, bastam Python 3.10+ e a biblioteca padrão.

## Início rápido

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

Na CLI do Codex, revise e confie nos hooks do plugin em `/hooks`; depois inicie uma **nova Task**. Coloque esta linha no início da mensagem:

```text
run-budget:start tokens=100k

Implement the feature and run the relevant checks.
```

`run-budget:status` mostra o estado; `run-budget:halt reason="operator pause"`, `run-budget:resume tokens=200k` e `run-budget:off` controlam o orçamento. [Todos os comandos e exemplos](README.md#commands-by-task) · [Projeto e regras](docs/DESIGN.md).

## Limites

O Codex não oferece um hook antes de toda solicitação ao modelo; ferramentas hospedadas podem não passar pelos hooks locais. Os contadores podem chegar após uma ação, então um turno pode ultrapassar o orçamento antes de HALT ser observado. São limites orientadores, sem garantia de faturamento exato, excesso zero ou aplicação universal. [Validação e limites](docs/VALIDATION.md).

[README completo em inglês](README.md) · [Índice da documentação](docs/README.md) · [Idiomas](docs/LOCALIZATION.md) · [Segurança](SECURITY.md)

Projeto comunitário independente; não é um produto da OpenAI ou da Microsoft. MIT © EasyVibeCoding contributors.
