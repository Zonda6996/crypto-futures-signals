# ALT-MULTITF-005: сборка через GitHub Actions

## Что это решает

Долгая загрузка, нормализация, упаковка и публикация выполняются на GitHub runner, а не внутри v0-чата. Поэтому закрытие чата или окончание кредитов v0 не стирает код и не влияет на уже запущенный workflow. GitHub Actions использует минуты GitHub Actions; лимиты вашего тарифа GitHub всё равно применяются.

Workflow не запускает Phase 2, сигналы, backtest, PnL, поиск параметров и не читает holdout.

## Однократно добавьте workflow через GitHub

GitHub App, которой пользуется v0, не имеет права менять `.github/workflows/*`, поэтому готовый workflow сохранён безопасным шаблоном: [`docs/alt-multitf-005.workflow-template.yml`](./alt-multitf-005.workflow-template.yml).

1. На сайте GitHub откройте нужную ветку репозитория.
2. Нажмите **Add file** → **Create new file**.
3. В имени файла укажите точно `.github/workflows/alt-multitf-005.yml`.
4. Откройте шаблон выше через **Raw**, скопируйте всё содержимое и вставьте в новый файл без изменений.
5. Нажмите **Commit changes** и сохраните в эту же ветку. После этого workflow появится во вкладке **Actions**.

Это единственный ручной шаг: весь исполняемый Python/Node-код, тесты и документация уже находятся в ветке.

## Однократная настройка Public Vercel Blob

1. Откройте Vercel Dashboard и выберите проект.
2. В Storage создайте отдельный Blob store с публичным доступом. Нужен именно **Public**, потому что другой аккаунт должен восстанавливать архив без секрета.
3. Получите read/write token этого store. Никому его не отправляйте и не вставляйте в чат.
4. На GitHub откройте `Zonda6996/crypto-futures-signals` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
5. Имя секрета должно быть точно `BLOB_READ_WRITE_TOKEN`, значение — read/write token.
6. Сохраните secret. GitHub не покажет значение повторно — это нормально.

## Первый запуск

1. Откройте GitHub → вкладка **Actions**.
2. Выберите **Build and publish ALT-MULTITF-005**.
3. Нажмите **Run workflow** и выберите ветку с этим workflow.
4. Для полностью чистой первой сборки выберите `restart`. `resume_run_id` оставьте пустым.
5. После завершения откройте run summary. Успешный run показывает публичный URL, SHA-256, размер и `Anonymous full-download verification: PASS`.
6. Скачайте artifact `alt-multitf-005-release-<run id>`. После реального PASS скопируйте `verified-release.json` в `docs/altcoin-multitf-005-blob.json` отдельным коммитом.

## Если запуск упал

Каждый run в шаге `always()` пытается загрузить artifact `alt-multitf-005-checkpoint-<run id>`. Откройте упавший run и скопируйте его числовой ID из URL: `.../actions/runs/123456789`, где ID — `123456789`.

Запустите workflow ещё раз:

- mode: `resume`;
- resume_run_id: ID предыдущего run;
- workers: обычно `12`.

Workflow скачает checkpoint, проверит version/protocol/config hash и checksums уже полученных файлов. Совместимые проверенные файлы не скачиваются повторно. Повреждённый или относящийся к другой спецификации checkpoint отклоняется. Если checkpoint artifact отсутствует (например, runner был жёстко остановлен по timeout до шага upload), используйте предыдущий доступный run или `restart`.

`restart` намеренно удаляет локальный checkpoint и начинает новую чистую сборку. Старые GitHub artifacts и публичный content-addressed Blob при этом не удаляются.

## Работа из другого аккаунта

Другому v0-аккаунту достаточно открыть тот же репозиторий, ветку/commit и прочитать эту инструкцию. Для скачивания и restore финального Public Blob token не нужен:

```bash
python scripts/restore_altcoin_multitf_005.py --metadata docs/altcoin-multitf-005-blob.json --root data
```

Для запуска Actions другому GitHub-аккаунту нужны права на репозиторий. Secret остаётся внутри GitHub repository settings: его не надо переносить в промпт, показывать другому v0-чату или копировать в код. Если новый аккаунт работает с fork, repository secrets автоматически в fork не переходят — в fork нужно создать собственный Public Blob store/secret либо запускать workflow в исходном репозитории с выданными правами.

## Что является окончательным успехом

Код и unit tests сами по себе ещё не означают, что архив опубликован. Release считается готовым только когда реальный GitHub Actions run одновременно:

- построил frozen inventory `3 291` файлов / `568 466 246` raw bytes;
- проверил manifests;
- загрузил `altcoin-multitf-005/<SHA256>.tar.gz` в Public Blob;
- полностью скачал этот URL без Authorization;
- повторно получил тот же размер и SHA-256;
- создал verified release artifact и PASS summary.
