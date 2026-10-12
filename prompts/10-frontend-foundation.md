# Этап 10 — Frontend foundation и onboarding

## Цель

Создать качественную, адаптивную основу React-приложения и довести первый запуск до первого счёта.

## Выполни

- Сначала определи и зафиксируй в `docs/UI.md` визуальное направление: спокойный финансовый инструмент, высокая плотность данных без перегруза, ясная иерархия, выразительная типографика с кириллицей, доступный контраст. Не копируй generic admin template.
- Создай design tokens и базовые компоненты: buttons, inputs, money/date controls, dialog/drawer, table/list, empty/error/loading states, toast, chart palette.
- Реализуй app shell, responsive navigation, route boundaries, global error handling, session bootstrap и generated API client integration.
- Реализуй login и onboarding: мастер bootstrap при пустом инстансе, профиль, валюта, locale/timezone, первый счёт и начальный остаток.
- Денежный input работает со строкой/Decimal contract, корректно обрабатывает locale и не превращает значение в JS float для отправки.
- Добавь keyboard navigation, visible focus, semantic labels, reduced motion и responsive layout от 360 px.
- Напиши component/integration tests и Playwright smoke для login/onboarding. Добавь Storybook или лёгкий component catalog только если он реально поддерживается тестами и командами.

## Приёмка

- Новый пользователь проходит путь до dashboard без ручных API-вызовов.
- Loading/empty/error/session-expired состояния спроектированы, а не оставлены случайными.
- Основные действия доступны клавиатурой и не ломаются на 360 px.
- Frontend lint, typecheck, tests и production build зелёные.
- Обновлён `STATUS.md`; создан commit `feat(10): build accessible application foundation`.

