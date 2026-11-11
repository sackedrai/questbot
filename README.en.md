# QuestBot

Telegram bot with daily mini-quests and player ratings.

[Версия на русском →](README.md)

Each player receives one short quest per day, answers in a minute, and earns points. Leaderboards, streaks, levels, and PvP duels one-on-one.

## Features

- Seven mini-games: quiz, fast question, chronology, riddle, word guessing, truth or false, counting
- Quests don't repeat: the bot doesn't give what you've already completed
- Adaptive difficulty: the bot picks the level automatically based on your results
- Next quest arrives exactly 24 hours after the previous one
- Ratings: points and quests per day, per week, all-time, and separately PvP
- PvP duels: challenge link, same quest for both, higher score wins
- Settings: time zone, notifications
- Weekly summary and a hint of who to catch up with
- Quest can be taken later, or skipped without penalty
- Chat cleans itself: only the current screen remains
- Streak protection: one missed day doesn't reset it
- Achievements: quests, streak, duel wins
- Your own questions: submit a task, after moderation it joins the common quest bank

## How to play

| Action | Command |
|---|---|
| Daily quest | `/quest` |
| Profile and statistics | `/profile` |
| Rating | `/top` |
| Challenge to duel | `/pvp` |
| Submit your question | `/ask` |
| My questions | `/myquestions` |
| Weekly summary | `/week` |
| Battle history | `/battles` |
| Settings | `/settings` |
| Time to next quest | `/next` |
| Help | `/help` |

## Getting started

Need Python 3.10+ and a token from [@BotFather](https://t.me/BotFather).

In `.env`:

```
BOT_TOKEN=1234567890:AA...
```

Then:

```bash
python -m venv .venv
pip install -r requirements.txt
python -m bot
```

Player data is stored in a SQLite file next to the code.

## Your own content

All quests are in `bot/content.py`, format is simple with examples in the file.

## Privacy

The database backup in the repository is encrypted. Telegram usernames and names are not stored: players only set a name for the rating.

## Status

Alpha version, running 24/7 on GitHub Actions. Covered by 497 autotests. Ideas and plans — in issues.
