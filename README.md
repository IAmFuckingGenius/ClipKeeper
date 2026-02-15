# ClipKeeper

Современный менеджер буфера обмена для Linux (GTK4 + Libadwaita): история текста и изображений, трей, хоткеи, бэкапы и локализация.

## Для чего проект

ClipKeeper делает буфер обмена удобным для повседневной работы:

- быстро открыть/скрыть окно истории
- найти и повторно использовать старые элементы
- закреплять важное, собирать сниппеты, отмечать избранное
- хранить данные локально и делать резервные копии

## Поддержка ОС и окружений

| Платформа | Статус | Примечание |
| --- | --- | --- |
| Linux + GNOME (Wayland) | Поддерживается | Рекомендуемая среда, глобальный хоткей через `gsettings`. |
| Linux + GNOME (X11) | Поддерживается | Работает стабильно, позиционирование окна зависит от WM. |
| Linux + Hyprland (Wayland) | Поддерживается | Хоткей через `~/.config/hypr/clipkeeper.conf`. |
| Linux + KDE (Wayland/X11) | Частично | Приложение работает, авто-настройка хоткея пока без KDE backend. |
| Другие DE/WM | Частично | База работает, хоткей обычно нужно назначать вручную. |
| Windows / macOS | Не поддерживается | Проект Linux-only. |

## Возможности

- Мониторинг буфера: текст и изображения
- Поиск и фильтры по категориям
- Избранное, закреплённые элементы, сниппеты
- Маскирование чувствительных данных
- Превью и действия по элементам (редактирование/перевод/QR и др.)
- Редактор изображений (обрезка/blur)
- Импорт/экспорт JSON (включая изображения)
- Ограничение размера истории с автоочисткой
- Автобэкап истории с ротацией
- Управление через системный трей
- Локализация интерфейса (`ru`, `en`)
- Глобальная горячая клавиша из настроек (GNOME + Hyprland)

## Текущие ограничения и траблы

- На Wayland композитор может ограничивать точное позиционирование popup-окна.
- Поведение трея зависит от поддержки AppIndicator в конкретной среде.
- Автоприменение хоткея пока реализовано только для:
  - GNOME (`gsettings`)
  - Hyprland (`clipkeeper.conf` + `source`)
- Для KDE и некоторых WM хоткей лучше назначать вручную на команду `clipkeeper --toggle`.
- OCR и QR — опциональные возможности, зависят от дополнительных пакетов.

## Установка

```bash
bash install.sh
```

Что делает инсталлятор:

- ставит зависимости (для `apt`-систем)
- создает команду `~/.local/bin/clipkeeper`
- ставит desktop entry и автозапуск
- устанавливает иконку
- пытается назначить хоткей по умолчанию (`Super+C`)

Установка без зависимостей:

```bash
bash install.sh --skip-deps
```

### Установка одной командой через curl (без git clone)

```bash
curl -fsSL https://raw.githubusercontent.com/IAmFuckingGenius/ClipKeeper/main/bootstrap-install.sh | \
  bash -s -- --repo IAmFuckingGenius/ClipKeeper --ref main
```

Для установки без зависимостей:

```bash
curl -fsSL https://raw.githubusercontent.com/IAmFuckingGenius/ClipKeeper/main/bootstrap-install.sh | \
  bash -s -- --repo IAmFuckingGenius/ClipKeeper --ref main --skip-deps
```

## Запуск

```bash
clipkeeper
```

CLI-команды:

- `clipkeeper --show`
- `clipkeeper --toggle`
- `clipkeeper --daemon`
- `clipkeeper --quit`
- `clipkeeper --set-hotkey "Super+C"`

## Если хоткей не применился автоматически

Назначь вручную в настройках DE на команду:

```bash
clipkeeper --toggle
```

## Где лежат данные

- База: `~/.local/share/clipkeeper/history.db`
- Изображения: `~/.local/share/clipkeeper/images`
- Бэкапы: `~/.local/share/clipkeeper/backups`
- Команда запуска: `~/.local/bin/clipkeeper`

## Структура проекта

- `src/main.py` — точка входа и CLI
- `src/application.py` — lifecycle приложения
- `src/window.py` — основное окно
- `src/settings.py` — окно настроек
- `src/monitor.py` — монитор буфера обмена
- `src/database.py` — БД, миграции, импорт/экспорт, бэкапы
- `src/tray.py` — интеграция с треем
- `src/hotkeys.py` — backends горячих клавиш (GNOME/Hyprland)
- `src/i18n.py` — локализация
- `data/style.css` — стили интерфейса
- `data/locales/*.json` — переводы

## Git и релиз

Привязка к репозиторию:

1. `git remote add origin https://github.com/IAmFuckingGenius/ClipKeeper.git`
2. `git push -u origin main`

Релиз (пример `v1.0.0`):

1. `git tag -a v1.0.0 -m "ClipKeeper v1.0.0"`
2. `git push origin v1.0.0`
3. Создать Release в GitHub UI по тегу `v1.0.0`

В проект уже добавлены файлы для репозитория:

- `.gitignore`
- `.gitattributes`
- `.editorconfig`
- `CONTRIBUTING.md`

## Разработка

Быстрая проверка Python-файлов:

```bash
python3 -m py_compile src/*.py
```

Гайд по контрибьюту: `CONTRIBUTING.md`

## Ближайший roadmap

- Нативный backend хоткеев для KDE
- Улучшение логики позиционирования окна на Wayland
- Автотесты для импорт/экспорт и хоткей-backends
- Опциональный защищенный режим экспорта
