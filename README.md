# Telegram Shell Bot

This bot enables user to make system calls via Telegram.

I'm used to send a lot of commands to my servers, and I don't want to open an SSH session each time. Since I use Telegram a lot, I created this bot to help me sending commands.

## Setup

```shell
python3 -m venv env # Create a virtual environment...
source env/bin/activate # ...and activate it (Linux)
python3 -m pip install -r requirements # Install dependencies
sl # Enjoy the train (optional but recommended)
```

## Configuration

Create `./keys.py`:

```python
TOKEN = "0123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
API_ID = "12345678"
API_HASH = "c2306f38edaeb5694c37cdf52b7d573d"
```

You can retrieve the bot's `TOKEN` via [BotFather](https://BotFather.t.me) and the `API_ID` and `API_HASH` at [my.telegram.org](https://my.telegram.org/apps).

Create `./config.py`:

```python
# Enter whatever name you want here:
BOTNAME: str = "tgshellbot"
# Telegram IDs of the users who can use the bot:
ADMINS: list[int] = [448025569]
# You can use the private chat with the bot as log chat,
# or, create a group, make the bot join, send /id and get
# the group ID there
LOG_CHAT: int = ADMINS[0] if ADMINS else None
# LOG_CHAT = -1001959731756
```

If you don't know your Telegram ID, you can start the bot with `ADMINS = []` and `LOG_CHAT = None` and send `/id` once the bot.

Run the bot:

```shell
source env/bin/activate
./main.py
```

## Credits

Used libraries:

- [`pyrogram`](https://pyrogram.org/): Telegram client

## Known issues

- When the output exceeds the maximum allowed length (3840 characters):
  
  - newly created messages won't send any input when replied to;
  
  - the output will be split exactly at the 3840th character, it's planned to make it split in the last '\n' available, the position of which may vary.
