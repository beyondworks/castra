# Castra

Claude Code에서 요청을 관찰·구현·검증까지 이어가도록 돕는 개발 하네스입니다. 작업 상태와 근거를 세션별로 보존합니다. 비공개 시스템 프롬프트 복제, 모델 가중치 변경, Astra와의 성능 동등성을 주장하지 않습니다.

## 호출

독립 설치는 `/castra run <요청>`, 플러그인은 `/castra:castra run <요청>`입니다. 일반 입력 `castra: run <요청>`도 UserPromptSubmit에서 연결됩니다.

- `run`: 사용자에게 문제가 나타나는 지점부터 관찰하고, 원인을 구분하는 검사 → 수정 → 같은 지점 재확인.
- `reframe`: 기존 목적을 유지하고 실제 실행 경로·공통 증상부터 가설을 반증할 관찰을 다시 선택.
- `finish`: 관련 누락, 상태 전환·재실행·실패 복구까지 확인하고 완결.
- `review`: 요청된 변경과 소비자를 읽고 근거 있는 결함을 보고. 별도 수정 요청 없이는 읽기 전용.
- `verify`: 미검증 파일과 실제 검사를 연결하고 성공·실패 증거 기록.
- `resume`: 해당 세션의 체크포인트·현재 파일·브랜치를 대조해 재개.
- `status`: 확인·미검증·보류를 구분해 보고.
- `castra: plain`: 별도 작업 흐름을 활성화하지 않음. 권한이나 기존 근거를 지우지 않음.

Fable·Opus 모두 현재 선택한 모델과 같은 계약을 사용합니다. 모델 이름으로 능력·컨텍스트 용량을 추정하지 않습니다. 깊이 있는 판단은 요구하되 내부 사고 과정 전사를 요구하지 않습니다.

## 기능으로 보완하는 부분

| 기능 | 실제 역할 | 한계 |
|---|---|---|
| 시작 훅 | 짧은 작업 계약·현재 세션 id·스크립트 경로·체크포인트 복원 | 기록은 과거 근거이며 새 권한이 아님 |
| 계약 갱신 | 일반 프롬프트에서 바뀐 계약을 세션당 한 번 주입. 명시 호출로 다시 복원 | 전달 기록이지 모델의 준수 보장은 아님 |
| 변경 추적 | Edit/Write 등 변경을 세션별 미검증 상태로 기록 | 임의 셸 쓰기·검사 의미까지 자동 추론하지 않음 |
| 검증 실행기 | 명시한 파일 해시·검사 종료코드·시간 기록, 제한된 진단 출력 | 검사 범위 적절성은 에이전트가 판단 |
| 종료 훅 | 미검증 상태에 한 번 복구 기회 제공, 재진입은 제한 | 보류·한도 도달을 성공으로 바꾸지 않음 |
| 예산 훅 | 현재 transcript의 제한된 꼬리와 명시한 용량으로 경고 | 용량 미설정은 unknown. 새 세션 자동 생성 불가 |
| 위험·발행 훅 | 위험 문법을 분류하고 단순 발행 명령의 대상 커밋 CI 조회 | 샌드박스나 모든 위험·필수 CI를 보장하는 장치가 아님 |

사용자 승인과 작업 목적은 세션 중 유지됩니다. 후속 메시지는 기존 목적의 수정으로 반영합니다. 필요한 로컬 작업은 계속하되, 운영 변경·외부발송·파괴적 작업의 권한을 임의 확장하지 않습니다. 수정한 소스와 사용자가 실행하는 설치본은 다른 검증 대상입니다.

## 설치

Python 3.10 이상. 두 방식 중 하나만 사용합니다.

```sh
python3 install.py --dry-run
python3 install.py
python3 install.py --check
```

기존 설치를 갱신하며 다른 훅·설정·소유권 없는 thinking-map은 보존합니다. 수정된 관리 파일이나 symlink는 덮어쓰지 않습니다. 백업·롤백 지도는 `~/.castra/backups/`에 남습니다. v0.7 manifest에는 훅 해시가 없으므로 이전 커밋과 바이트 일치를 확인한 훅만 소유권 해시로 보강한 후 이관합니다. 새 등록은 Claude Code를 재시작해야 적용됩니다. 이미 route 훅을 등록한 세션은 다음 입력에서 변경된 계약을 한 번 받습니다. 일반 실행에도 같은 기준을 적용하며 reframe/finish를 매번 입력할 필요는 없습니다.

플러그인 방식은 `claude plugin validate .` 후 `claude --plugin-dir /절대경로/castra`입니다. 독립 설치 훅이 켜진 프로필에 플러그인을 중복 로드하지 않습니다. 별도 MCP나 권한 우회 설정은 필요하지 않습니다.

`--check`는 설치 파일·설정·격리 입력 검사를 확인합니다. 실제 Claude 이벤트 발동은 새 Claude 실행에서 별도로 확인해야 합니다. macOS 설치본 실험과 Windows/Linux 실기기 확인은 구분합니다.

## 상태·검증·재개

시작 훅이 알려준 실제 SESSION_ID와 스크립트 경로를 사용합니다.

```sh
python3 ~/.castra/scripts/castra_runtime.py status --session SESSION_ID
python3 ~/.castra/scripts/castra_runtime.py verify --session SESSION_ID --file src/example.py -- python3 -m unittest tests.test_example
python3 ~/.castra/scripts/castra_notes.py checkpoint --session SESSION_ID --goal '사용자 결과' --progress '확인한 근거' --next '다음 단계'
python3 ~/.castra/scripts/castra_notes.py read --session SESSION_ID
```

검증 출력은 제한된 진단 꼬리만 반환하며 알려진 시크릿 형태를 최선 노력으로 가립니다. 자격증명을 출력하는 검사를 실행하지 않습니다. 명령과 출력은 영속 장부에 저장하지 않습니다. `block`/`defer`는 이유 코드와 함께 미해결로 남깁니다. 장부를 직접 편집해 성공을 만들지 않습니다.

상태는 작업 폴더 `.castra/` 아래 세션 id 해시로 격리됩니다. 과거 `.astra`·unscoped 기록은 보존하며 자동으로 다른 세션에 합치지 않습니다. 창을 넘어 전달할 때 이전 세션 id를 명시해 읽습니다. 실제 용량을 아는 경우에만 `CASTRA_CONTEXT_WINDOW`를 지정합니다.

## 확인 범위

`PYTHONDONTWRITEBYTECODE=1 python3 tests/run.py`로 회귀검사를 실행합니다. 작은 실제 모델 과제는 훅 연결을 확인하며 모델 간 품질 비교나 성능 극대화의 증거가 아닙니다. Claude CLI에 `--brief`가 실제로 있으면 통신 도구를 활용할 수 있지만, 없는 도구를 하네스가 만들어 주거나 긴 도구 호출 중 자동 대화를 보장하지는 않습니다.

공식 계약: [hooks](https://code.claude.com/docs/en/hooks), [plugins](https://code.claude.com/docs/en/plugins), [plugin reference](https://code.claude.com/docs/en/plugins-reference). 상세: [README.md](README.md).

자동 추적 대상은 일반 코드·CSS/SCSS/HTML/Vue/Svelte·노트북·CI workflow YAML·migration SQL/YAML입니다. 일반 Markdown/JSON/설정 파일은 제외하며 동작에 영향을 주면 명시적으로 검증합니다.
