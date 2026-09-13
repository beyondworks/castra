<!-- CASTRA:BEGIN — maintained by Castra; model-neutral runtime contract. -->
## Castra
SessionStart injects the execution contract and this session's runtime pointers. UserPromptSubmit refreshes a changed contract once per session; explicit Castra calls can restore it during a long task. `/castra` (standalone) or `/castra:castra` (plugin) supports run, review, verify, reframe, finish, resume and status. A literal `castra: <mode> <request>` also routes through UserPromptSubmit.
Use the session id and script directory supplied by the hook for checkpoints and verification. Hooks record pending edits and give a bounded recovery opportunity; they do not prove semantic correctness or create a new context window. If no runtime hint appears, verify installation with Castra's `install.py --check`; do not assume automatic controls ran.
The user's scope, platform permissions, secret handling and evidence preservation prevail. Model names never imply capacity or permissions. Local completion and production verification remain separate claims.
<!-- CASTRA:END -->
