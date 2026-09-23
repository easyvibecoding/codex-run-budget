# Codex Run Budget

**Codex Task와 하위 에이전트가 공유하는 토큰 예산 가드레일과 로컬 사용량 정보.**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português](README.pt.md)

Codex Run Budget은 부모 Task와 하위 에이전트가 하나의 예산을 공유하도록 하는 로컬 Codex 플러그인입니다. 턴별 사용량 기록, 범위를 지정한 Task 보고서, 계정 할당량 관찰, 선택적 워크플로 및 `codex exec` 활동 보기도 제공합니다. 예산 판단은 Python과 SQLite의 결정적 규칙을 따르며, 보고서를 조회하는 것만으로 예산이 시작되지는 않습니다.

## 주요 기능

- **공유 예산:** 부모 Task의 `session_id`를 실행 키로 사용해 하위 에이전트를 함께 집계합니다. STEER와 HALT는 지원되는 hook 경계에서 적용됩니다.
- **사용량 기록과 보고서:** 자동 턴 카드, 개별 Task, 에이전트 트리 또는 명시한 기간의 관찰값을 확인합니다. 근거가 부족하면 부분적 또는 알 수 없음 상태를 유지합니다.
- **할당량과 활동:** Codex 기본 계정 할당량을 읽고 필요할 때 워크플로와 프로젝트 범위의 `codex exec`를 관찰합니다. 계정 사용률은 Task별 청구액이 아닙니다.
- **로컬과 개인정보:** 원장은 허용된 카운터, 상태, 시각 및 해시된 식별자만 보관합니다. 프롬프트, 명령, 도구 내용을 의도적으로 저장하지 않습니다. 실행에는 Python 3.10+ 표준 라이브러리만 필요합니다.

## 빠른 시작

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

Codex CLI의 `/hooks`에서 플러그인 hook을 확인하고 신뢰한 뒤 **새 Task**를 시작합니다. Task 메시지 맨 앞에 다음을 입력합니다.

```text
run-budget:start tokens=100k

Implement the feature and run the relevant checks.
```

`run-budget:status`로 상태를 확인하고 `run-budget:halt reason="operator pause"`, `run-budget:resume tokens=200k`, `run-budget:off`로 제어합니다. [전체 명령과 예시](README.md#commands-by-task) · [설계와 규칙](docs/DESIGN.md).

## 적용 범위와 한계

Codex는 모든 모델 요청 전에 플러그인 hook을 제공하지 않습니다. hosted tools가 로컬 도구 hook을 거치지 않을 수도 있습니다. 사용량 카운터가 실행 후에 도착할 수 있어 HALT가 관찰되기 전에 한 턴에서 예산을 초과할 수 있습니다. 이 도구는 가드레일이며 정확한 청구, 초과량 0, 모든 작업의 차단을 보장하지 않습니다. [실제 설치 검증과 한계](docs/VALIDATION.md).

[영문 상세 README](README.md) · [문서 목록](docs/README.md) · [언어 안내](docs/LOCALIZATION.md) · [보안 정책](SECURITY.md)

독립 커뮤니티 프로젝트이며 OpenAI 또는 Microsoft 제품이 아닙니다. MIT © EasyVibeCoding contributors.
