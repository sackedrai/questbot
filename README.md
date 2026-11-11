# QuestBot

Telegram-бот с ежедневными мини-квестами и рейтингом игроков.  
Telegram bot with daily mini-quests and player ratings.

---

## 🇷🇺 Русский / English

## О боте / About

Каждый игрок получает один короткий квест в сутки, отвечает за минуту и получает очки. Есть таблица лидеров, серия дней, уровни и дуэли один на один.  
Each player receives one short quest per day, answers in a minute, and earns points. Leaderboards, streaks, levels, and PvP duels one-on-one.

## Что внутри / What's inside

- семь мини-игр: викторина, быстрый вопрос, хронология, загадка, угадай слово, правда или ложь, счёт  
- задания не повторяются: бот не выдаёт то, что ты уже проходил  
- сложность бот подбирает сам — по результатам игрока  
- следующий квест приходит ровно через 24 часа после предыдущего  
- рейтинг: очки и квесты за день, за неделю, за всё время, отдельно PvP  
- дуэли один на один: ссылка-вызов, общий квест, кто больше набрал  
- настройки: часовой пояс, уведомления  
- сводка за неделю и подсказка, кого догонять  
- квест можно взять и позже, а если не под силу — сдаться без штрафа  
- чат чистится сам: при смене экрана остаётся только текущий  
- серия дней с защитой: один пропущенный день её не обнуляет  
- достижения: награды за квесты, серию и победы в дуэлях  
- свои вопросы: предложи задание, после проверки оно попадёт в общий банк  

Seven mini-games: quiz, fast question, chronology, riddle, word guessing, truth or false, counting  
Quests don't repeat: the bot doesn't give what you've already completed  
Adaptive difficulty: the bot picks the level automatically based on your results  
Next quest arrives exactly 24 hours after the previous one  
Ratings: points and quests per day, per week, all-time, and separately PvP  
PvP duels: challenge link, same quest for both, higher score wins  
Settings: time zone, notifications  
Weekly summary and a hint of who to catch up with  
Quest can be taken later, or skipped without penalty  
Chat cleans itself: only the current screen remains  
Streak protection: one missed day doesn't reset it  
Achievements: quests, streak, duel wins  
Your own questions: submit a task, after moderation it joins the common quest bank

## Как играть / How to play

| Действие / Action | Команда / Command |
|---|---|
| Квест дня / Daily quest | `/quest` |
| Профиль и статистика / Profile and statistics | `/profile` |
| Рейтинг / Rating | `/top` |
| Вызвать на дуэль / Challenge to duel | `/pvp` |
| Предложить свой вопрос / Submit your question | `/ask` |
| Мои вопросы / My questions | `/myquestions` |
| Сводка за неделю / Weekly summary | `/week` |
| История боёв / Battle history | `/battles` |
| Настройки / Settings | `/settings` |
| Время до следующего квеста / Time to next quest | `/next` |
| Справка по правилам / Help | `/help` |

## Запуск / Getting started

Нужен Python 3.10+ и токен от [@BotFather](https://t.me/BotFather).  
Need Python 3.10+ and a token from [@BotFather](https://t.me/BotFather).

В `.env`:  
In `.env`:

```
BOT_TOKEN=1234567890:AA...
```

Затем:  
Then:

```bash
python -m venv .venv
pip install -r requirements.txt
python -m bot
```

Данные игроков лежат в SQLite-файле рядом с кодом.  
Player data is stored in a SQLite file next to the code.

## Свой контент / Your own content

Все задания — в `bot/content.py`, формат простой, с примерами в файле.  
All quests are in `bot/content.py`, format is simple with examples in the file.

## Приватность / Privacy

Бэкап базы в репозитории зашифрован. Telegram-ники и имена в базе не сохраняются: игрок задаёт только имя для рейтинга.  
The database backup in the repository is encrypted. Telegram usernames and names are not stored: players only set a name for the rating.

## Статус / Status

Альфа-версия, работает круглосуточно на GitHub Actions. Покрыта 497 автотестами. Идеи и планы — в issues.  
Alpha version, running 24/7 on GitHub Actions. Covered by 497 autotests. Ideas and plans — in issues.

---

Если нашли ошибку — создайте issue: https://github.com/sackedrai/questbot/issues  
If you found a bug — create an issue: https://github.com/sackedrai/questbot/issues
